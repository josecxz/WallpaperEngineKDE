// Ejecutor GL de un plan de render, portado desde tools/glexec.c.
//
// El plan se carga una vez y se ejecuta cada fotograma con un tiempo distinto,
// volcando sobre un FBO que nos da Qt.
//
// Estructura en tres fases, y el reparto entre ellas es lo que decide el coste:
//
//   loadPlan()   parsea el texto  -> estructuras con cadenas. Sin GL.
//   initialize() crea los recursos GL, compila los programas y RESUELVE el
//                plan: nombres -> indices, uniforms -> localizaciones. A
//                partir de aqui no queda ni una cadena por mirar.
//   render()     solo bindea y dibuja. Cero parseo, cero asignaciones.
//
// La fase de resolucion existe porque todo lo que se resolvia antes por
// fotograma era invariante: 403 glGetUniformLocation (~67k/s a 166 fps), 33
// QString/QByteArray temporales y 22 KB de memcpy, cada fotograma, para
// obtener siempre el mismo resultado.

#pragma once

#include <QByteArray>
#include <QHash>
#include <QString>
#include <QVector>

// Los identificadores de GL son `unsigned int` y las localizaciones `int`.
// Se usan los tipos del lenguaje en vez de declarar `using GLuint = ...` aqui:
// esta cabecera no incluye GL, y falsificar sus nombres en el ambito global
// choca con el GL/gl.h real en cuanto alguien lo incluya despues.
using GlName = unsigned int;      // glGenTextures, glCreateProgram...
using GlLocation = int;           // glGetUniformLocation (-1 = no existe)

class GlExecutor
{
public:
    GlExecutor() = default;
    ~GlExecutor();

    // Posee handles de GL y los libera en el destructor: copiarlo provocaria
    // una doble destruccion. Regla de cinco, resuelta prohibiendo copia y
    // movimiento, que es lo que esta clase necesita.
    GlExecutor(const GlExecutor &) = delete;
    GlExecutor &operator=(const GlExecutor &) = delete;
    GlExecutor(GlExecutor &&) = delete;
    GlExecutor &operator=(GlExecutor &&) = delete;

    // Parsea el plan. No toca GL: se puede llamar sin contexto activo.
    // `error` es opcional; puede ser nullptr.
    bool loadPlan(const QString &path, QString *error = nullptr);

    // Crea recursos GL, compila programas y resuelve el plan. Requiere
    // contexto activo. `error` es opcional.
    bool initialize(QString *error = nullptr);

    // Ejecuta todos los pases y compone sobre `targetFbo`, llevando el lienzo
    // del autor a viewW x viewH segun el encaje configurado.
    void render(GlName targetFbo, int viewW, int viewH, float time);

    // Como se lleva la escena a la pantalla. La escena se dibuja SIEMPRE al
    // tamano del lienzo que declara su autor, que casi nunca es el de la
    // pantalla ---99 de las 125 escenas del corpus son 16:9---, asi que este
    // ultimo paso decide que parte se ve. No cambia lo que cuesta dibujarla:
    // eso es un parametro del plan, no del ejecutor.
    enum Encaje {
        Cubrir  = 0,   // llena la pantalla recortando lo que sobra
        Encajar = 1,   // se ve entera, con barras donde falta
        Estirar = 2,   // llena la pantalla deformando la escena
    };
    // `zoom` multiplica la escala resultante y `desp` elige que trozo se ve
    // cuando sobra escena: -1 es todo a un lado, 0 el centro, +1 al otro.
    void setFit(int encaje, float zoom, float despX, float despY);
    // Color de las barras. Va aqui y no en el QML porque el item se compone
    // sin mezcla alfa: lo que no pintemos sale negro, no transparente.
    void setBarColor(float r, float g, float b);

    void releaseResources();

    // Numeros de solo lectura, para diagnostico.
    int passCount() const { return m_passCount; }
    // Diagnostico de las mallas puppet: cuantas se subieron y cuantos pases
    // las referencian. Si el segundo es 0 el plan no las esta pidiendo; si el
    // primero es 0 no llegaron a la GPU.
    int meshCount() const { return m_meshCount; }
    int meshPassCount() const { return m_meshPassCount; }
    int meshAnimCount() const { return m_meshAnimCount; }
    // Sistemas de particulas cargados y piezas de ellos que no se reconocieron.
    int psysCount() const { return m_psysCount; }
    int psysUnknownParts() const { return m_psysUnknownParts; }
    int canvasWidth() const { return m_canvasW; }
    int canvasHeight() const { return m_canvasH; }
    int liveUniformCount() const { return m_liveUniforms; }
    int initMillis() const { return m_initMs; }
    double diagCompoMean() const { return m_diagCompoMean; }

    // Milisegundos de GPU por fotograma, medidos por la GPU misma. El `fps`
    // del HUD no vale para esto: sale del reloj de QML, y como las llamadas a
    // GL son asincronas la CPU encola y vuelve enseguida aunque la GPU se
    // quede atras. Con el fondo 4K medimos 166 fps en el HUD mientras la
    // integrada estaba al 98%. Negativo mientras no haya medida.
    double diagGpuMs() const { return m_gpuMs; }
    // Cuantas veces fallo al abrir la consulta; >0 explica un
    // "sin medida" que si no seria mudo.
    int diagGpuFallos() const { return m_gpuFallos; }
    int diagGpuSaltos() const { return m_gpuSaltos; }
    int diagGpuAjena() const { return m_gpuAjena; }
    int diagBlitError() const { return m_diagBlitError; }
    int targetCount() const { return m_diagTargets; }
    QString title() const { return m_title; }
    int droppedUniformCount() const { return m_droppedUniforms; }
    QString log() const { return m_log; }

private:
    // Indices especiales de destino/origen. Los buffers con nombre viven en
    // m_targets con indice >= 0.
    static constexpr qsizetype kCompo = -1;   // buffer del objeto en curso
    static constexpr qsizetype kScene = -2;   // acumulado de todos los objetos

    // Los dos `Premul*` son los de particula: se diferencian de sus homologos
    // solo en el canal alfa, que acumulan sin elevar al cuadrado. Ver
    // `set_blend` en tools/glexec.c, que lleva el porque completo.
    enum class Blend { None, Normal, Additive, PremulAlpha, PremulAdditive };
    enum class Source { Texture, Target, Previous };

    // Como se compone el buffer del objeto sobre la escena.
    enum class Compose { Normal, Additive, PremulOver, PremulAdd };

    // Un sampler ya resuelto: sin cadenas, sin busquedas.
    struct Sampler {
        Source source = Source::Previous;
        GlName texture = 0;         // Source::Texture
        qsizetype targetIndex = kCompo; // Source::Target
        GlLocation location = -1;
        int unit = 0;
    };

    struct Uniform {
        GlLocation location = -1;
        int count = 0;          // 1..4 o 16
        bool timeMarker = false;
        float v[16] = {};
    };

    struct Op {
        enum Kind { Pass, Copy, BeginObject } kind = Pass;
        bool copyBackground = false;    // BeginObject
        // Colocacion del objeto en el lienzo (BeginObject). Los pases corren
        // en el espacio de la capa; esta matriz se aplica una unica vez, al
        // componer el objeto sobre la escena.
        float placement[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
        // Como se lleva el buffer del objeto a la escena. colorBlendMode 31 da
        // `Additive`; un sistema de particulas da uno de los `Premul*`, porque
        // su buffer ya trae el color multiplicado por el alfa.
        Compose compose = Compose::Normal;
        // La capa no se compone: solo deja su resultado en un buffer con nombre.
        bool soloBuffer = false;
        // Pass
        QString vert, frag;             // solo hasta initialize()
        QString targetName;             // idem
        QVector<QByteArray> samplerNames;
        QVector<QByteArray> samplerSources;
        QVector<QByteArray> uniformNames;
        Blend blend = Blend::Normal;
        // Malla puppet a dibujar, o -1 para el quad a pantalla completa. Solo
        // el pase base de un objeto con puppet trae malla; los de efecto son
        // post-proceso y siguen usando el quad.
        int mesh = -1;
        // Sistema de particulas a dibujar, o -1. Manda sobre `mesh`: son
        // excluyentes, un objeto es una cosa o la otra.
        int psys = -1;
        GlName program = 0;
        qsizetype targetIndex = kCompo;
        QVector<Sampler> samplers;
        QVector<Uniform> uniforms;
        // Copy: -1 = compuesto del objeto
        qsizetype copySrc = kCompo, copyDst = kCompo;
        QString copySrcName, copyDstName;
        // "p046.frag -> _downscaled1", solo para WE_TRACE_PASES. Se compone
        // en resolve() porque targetName se descarta justo despues.
        QString etiqueta;
    };

    struct Target {
        GlName tex = 0;
        GlName fbo = 0;
        int w = 0, h = 0;
    };

    struct TexSpec {
        QString path;
        int w = 0, h = 0;
        GlName id = 0;
    };

    // Malla puppet. El fichero trae los vertices intercalados (posicion vec3 +
    // UV vec2, el mismo layout que el quad, para que los shaders no cambien) y
    // detras los indices u16.
    struct MeshSpec {
        QString path;
        int vertexCount = 0;
        int indexCount = 0;
        GlName vao = 0, vbo = 0, ibo = 0;

        // Animacion por huesos. Vacio si la malla va en pose de reposo.
        int boneCount = 0;
        int keyCount = 0;
        float duration = 0.0f;
        QVector<float> bind;        // (nverts, 5) pose de reposo + UV
        QVector<quint16> boneIdx;   // (nverts, 4)
        QVector<float> weights;     // (nverts, 4)
        QVector<float> mats;        // (nkeys, nbones, 12) ya compuestas
        QVector<float> skinned;     // destino del skinning, se reusa
        int lastKey = -1;           // ultima clave subida; -1 fuerza la subida

        bool animated() const { return boneCount > 0 && keyCount > 1; }
    };

    // Sistema de particulas. La simulacion la lleva `src/weparticles.c`,
    // compartido con el ejecutor offline; aqui solo vive lo que toca GL.
    struct PsysSpec {
        QString path;
        struct WeParticleSystem *sys = nullptr;
        GlName vao = 0, vbo = 0;
        int capacidad = 0;      // vertices que caben hoy en el VBO
    };

    // Malla lista para dibujar, o nullptr si el id no existe o no se subio.
    const MeshSpec *meshFor(int id) const;
    // Simula hasta `time`, sube los vertices y dibuja. false si no hay nada.
    bool drawPsys(int id, float time);

    // Deforma las mallas animadas y reescribe sus VBO. Una vez por fotograma,
    // no una por pase: varias pasadas comparten la misma malla.
    void skinMeshes(float time);

    qsizetype targetIndex(const QString &name);   // crea el target si no existe
    bool buildCompositeProgram();
    void beginObject();
    const Target &resolveTarget(qsizetype index) const;
    void flushObjectToScene();
    bool buildProgram(Op &op);
    void resolve(Op &op);

    QVector<Op> m_ops;
    QHash<int, TexSpec> m_textures;
    QHash<int, MeshSpec> m_meshes;
    QHash<int, PsysSpec> m_psys;
    int m_meshCount = 0, m_meshPassCount = 0, m_meshAnimCount = 0;
    int m_psysCount = 0, m_psysUnknownParts = 0;
    QVector<Target> m_targets;              // indexable y estable
    QHash<QString, qsizetype> m_targetByName;
    Target m_compo[2];      // buffer del objeto en curso (ping-pong)
    Target m_scene;         // acumulado de todos los objetos
    GlName m_composite = 0; // programa para componer objeto -> escena
    GlLocation m_compositeMvp = -1;
    float m_placement[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
    Compose m_compose = Compose::Normal;
    bool m_soloBuffer = false;
    bool m_objectOpen = false;
    bool m_hasObjectMarks = false;
    int m_compoCur = 0;
    GlName m_vao = 0, m_vbo = 0;
    int m_canvasW = 1920, m_canvasH = 1080;
    // Encaje del lienzo en la pantalla. Los valores por defecto son lo que se
    // hacia antes de que fuera configurable: cubrir, sin zoom y centrado.
    int m_fit = Cubrir;
    float m_zoom = 1.0f, m_despX = 0.0f, m_despY = 0.0f;
    float m_bar[3] = {0.0f, 0.0f, 0.0f};
    quint64 m_diagFitSig = 0;   // ultimo encaje trazado, para no repetirlo
    int m_passCount = 0;
    int m_liveUniforms = 0;
    int m_initMs = 0;
    bool m_diagDone = false;
    int m_frame = 0;            // solo para la traza de WE_TRACE_FRAMES
    int m_objeto = 0;           // idem
    double m_diagCompoMean = -1;

    // Cronometro de GPU. Dos objetos de consulta alternos: se pregunta por el
    // del fotograma ANTERIOR, porque preguntar por el de ahora obligaria a
    // esperar a que la GPU acabe --- y esa espera es justo lo que falsearia la
    // medida.
    void gpuTimerBegin();
    void gpuTimerEnd();
    void gpuTimerPoll();
    GlName m_gpuQuery[2] = {0, 0};
    bool m_gpuPend[2] = {false, false};
    int m_gpuCur = 0;
    bool m_gpuActive = false;
    bool m_gpuOff = false;          // el driver no da GL_TIME_ELAPSED
    int m_gpuFallos = 0;
    int m_gpuSaltos = 0;
    int m_gpuAjena = 0;
    double m_gpuMs = -1;
    int m_diagBlitError = 0;
    int m_diagTargets = 0;
    int m_droppedUniforms = 0;
    bool m_ready = false;
    QString m_title;
    QString m_log;
};
