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

    // Ejecuta todos los pases y compone sobre `targetFbo`, escalando con
    // recorte para llenar viewW x viewH sin deformar.
    void render(GlName targetFbo, int viewW, int viewH, float time);

    void releaseResources();

    // Numeros de solo lectura, para diagnostico.
    int passCount() const { return m_passCount; }
    int canvasWidth() const { return m_canvasW; }
    int canvasHeight() const { return m_canvasH; }
    int liveUniformCount() const { return m_liveUniforms; }
    int initMillis() const { return m_initMs; }
    double diagCompoMean() const { return m_diagCompoMean; }
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

    enum class Blend { None, Normal, Additive };
    enum class Source { Texture, Target, Previous };

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
        // Pass
        QString vert, frag;             // solo hasta initialize()
        QString targetName;             // idem
        QVector<QByteArray> samplerNames;
        QVector<QByteArray> samplerSources;
        QVector<QByteArray> uniformNames;
        Blend blend = Blend::Normal;
        GlName program = 0;
        qsizetype targetIndex = kCompo;
        QVector<Sampler> samplers;
        QVector<Uniform> uniforms;
        // Copy: -1 = compuesto del objeto
        qsizetype copySrc = kCompo, copyDst = kCompo;
        QString copySrcName, copyDstName;
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

    qsizetype targetIndex(const QString &name);   // crea el target si no existe
    bool buildCompositeProgram();
    void beginObject();
    const Target &resolveTarget(qsizetype index) const;
    void flushObjectToScene();
    bool buildProgram(Op &op);
    void resolve(Op &op);

    QVector<Op> m_ops;
    QHash<int, TexSpec> m_textures;
    QVector<Target> m_targets;              // indexable y estable
    QHash<QString, qsizetype> m_targetByName;
    Target m_compo[2];      // buffer del objeto en curso (ping-pong)
    Target m_scene;         // acumulado de todos los objetos
    GlName m_composite = 0; // programa para componer objeto -> escena
    bool m_objectOpen = false;
    bool m_hasObjectMarks = false;
    int m_compoCur = 0;
    GlName m_vao = 0, m_vbo = 0;
    int m_canvasW = 1920, m_canvasH = 1080;
    int m_passCount = 0;
    int m_liveUniforms = 0;
    int m_initMs = 0;
    bool m_diagDone = false;
    double m_diagCompoMean = -1;
    int m_diagBlitError = 0;
    int m_diagTargets = 0;
    int m_droppedUniforms = 0;
    bool m_ready = false;
    QString m_title;
    QString m_log;
};
