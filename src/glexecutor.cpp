// GL_GLEXT_PROTOTYPES debe definirse antes de cualquier include: Qt
// arrastra GL/gl.h, y si llega primero no se declaran los prototipos de GL 2+.
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>

#include "glexecutor.h"
#include "weparticles.h"

#include <QElapsedTimer>
#include <QVarLengthArray>
#include <QFile>
#include <QOpenGLContext>

#include <algorithm>
#include <QTextStream>

#include <cmath>
#include <cstring>

namespace {

QByteArray readAll(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return {};
    return f.readAll();
}

GlName compileShader(const QString &path, GLenum stage, QString *log)
{
    const QByteArray src = readAll(path);
    if (src.isEmpty()) {
        *log += QStringLiteral("no se pudo leer %1\n").arg(path);
        return 0;
    }
    const GlName sh = glCreateShader(stage);
    const char *p = src.constData();
    glShaderSource(sh, 1, &p, nullptr);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetShaderiv(sh, GL_INFO_LOG_LENGTH, &len);
        QByteArray buf(qMax(len, 1), '\0');
        glGetShaderInfoLog(sh, buf.size(), nullptr, buf.data());
        *log += QStringLiteral("%1:\n%2\n").arg(path, QString::fromUtf8(buf));
        glDeleteShader(sh);
        return 0;
    }
    return sh;
}

// WE codifica el divisor de resolucion en el nombre del render target.
int divisorFromName(const QString &name)
{
    if (name.contains(QLatin1String("Half")))
        return 2;
    if (name.contains(QLatin1String("Quarter")))
        return 4;
    if (name.contains(QLatin1String("Eighth")))
        return 8;
    return 1;
}

void makeTarget(GlName *tex, GlName *fbo, int w, int h)
{
    glGenTextures(1, tex);
    glBindTexture(GL_TEXTURE_2D, *tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, *fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, *tex, 0);
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
}

} // namespace

GlExecutor::~GlExecutor()
{
    // glDelete* sin contexto activo es comportamiento indefinido, y un
    // destructor puede ejecutarse en cualquier momento del apagado. Si no hay
    // contexto se prefiere avisar y filtrar los handles: el proceso esta
    // terminando y el driver los recupera igual.
    if (!m_ready)
        return;
    if (QOpenGLContext::currentContext())
        releaseResources();
    else
        qWarning("GlExecutor: destruido sin contexto GL activo; "
                 "los recursos se liberan al cerrar el contexto");
}

// ── carga ───────────────────────────────────────────────────────────────────

bool GlExecutor::loadPlan(const QString &path, QString *error)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text)) {
        if (error)
            *error = QStringLiteral("no se pudo abrir el plan: %1").arg(path);
        return false;
    }

    m_ops.clear();
    m_textures.clear();
    // Los simuladores son memoria propia, no handles de GL: se pueden soltar
    // aqui, sin contexto activo.
    for (PsysSpec &p : m_psys)
        we_psys_free(p.sys);
    m_psys.clear();
    m_psysCount = m_psysUnknownParts = 0;
    m_passCount = 0;

    QTextStream in(&f);
    Op cur;
    bool inPass = false;

    while (!in.atEnd()) {
        const QString line = in.readLine().trimmed();
        if (line.isEmpty())
            continue;
        const QStringList tok = line.split(QLatin1Char(' '), Qt::SkipEmptyParts);
        const QString &kw = tok.first();

        if (kw == QLatin1String("title")) {
            m_title = line.mid(6);
        } else if (kw == QLatin1String("canvas") && tok.size() >= 3) {
            m_canvasW = tok[1].toInt();
            m_canvasH = tok[2].toInt();
        } else if (kw == QLatin1String("tex") && tok.size() >= 5) {
            TexSpec t;
            t.path = tok[2];
            t.w = tok[3].toInt();
            t.h = tok[4].toInt();
            m_textures.insert(tok[1].toInt(), t);
        } else if (kw == QLatin1String("mesh") && tok.size() >= 5) {
            MeshSpec m;
            m.path = tok[2];
            m.vertexCount = tok[3].toInt();
            m.indexCount = tok[4].toInt();
            // Los tres campos de animacion son opcionales: una malla sin
            // pistas se queda en pose de reposo y se sube una sola vez.
            if (tok.size() >= 8) {
                m.boneCount = tok[5].toInt();
                m.keyCount = tok[6].toInt();
                m.duration = tok[7].toFloat();
            }
            m_meshes.insert(tok[1].toInt(), m);
        } else if (kw == QLatin1String("psys") && tok.size() >= 3) {
            PsysSpec p;
            p.path = tok[2];
            m_psys.insert(tok[1].toInt(), p);
        } else if (kw == QLatin1String("object")) {
            Op op;
            op.kind = Op::BeginObject;
            op.copyBackground = tok.size() >= 2 && tok[1] == QLatin1String("1");
            if (tok.size() >= 18)
                for (int i = 0; i < 16; ++i)
                    op.placement[i] = tok[2 + i].toFloat();
            if (tok.size() >= 19)
                switch (tok[18].toInt()) {
                case 1:  op.compose = Compose::Additive; break;
                case 2:  op.compose = Compose::PremulOver; break;
                case 3:  op.compose = Compose::PremulAdd; break;
                default: op.compose = Compose::Normal; break;
                }
            // Capa que solo llena su buffer de composicion: se dibuja pero no
            // se compone sobre la escena, que la muestreara otra por nombre.
            op.soloBuffer = tok.size() >= 20 && tok[19] == QLatin1String("1");
            m_ops.append(op);
        } else if (kw == QLatin1String("copy") && tok.size() >= 3) {
            Op op;
            op.kind = Op::Copy;
            op.copySrcName = tok[1];
            op.copyDstName = tok[2];
            m_ops.append(op);
        } else if (kw == QLatin1String("pass")) {
            cur = Op();
            inPass = true;
        } else if (!inPass) {
            continue;   // output/dump y demas directivas de la version CLI
        } else if (kw == QLatin1String("prog") && tok.size() >= 3) {
            cur.vert = tok[1];
            cur.frag = tok[2];
        } else if (kw == QLatin1String("target") && tok.size() >= 2) {
            cur.targetName = tok[1];
        } else if (kw == QLatin1String("mesh") && tok.size() == 2) {
            // Dentro de un pase `mesh` lleva solo el id; en la cabecera lleva
            // ademas ruta y tamanos, y la rama de arriba pide 5 tokens.
            cur.mesh = tok[1].toInt();
        } else if (kw == QLatin1String("psys") && tok.size() == 2) {
            // Dentro de un pase `psys` lleva solo el id; en la cabecera lleva
            // ademas la ruta, y la rama de arriba pide 3 tokens.
            cur.psys = tok[1].toInt();
        } else if (kw == QLatin1String("blend") && tok.size() >= 2) {
            const QString &b = tok[1];
            if (b == QLatin1String("none") || b == QLatin1String("opaque"))
                cur.blend = Blend::None;
            else if (b == QLatin1String("additive"))
                cur.blend = Blend::Additive;
            else if (b == QLatin1String("premul_additive"))
                cur.blend = Blend::PremulAdditive;
            else if (b == QLatin1String("premul_alpha"))
                cur.blend = Blend::PremulAlpha;
            else
                cur.blend = Blend::Normal;
        } else if (kw == QLatin1String("sampler") && tok.size() >= 3) {
            cur.samplerNames.append(tok[1].toUtf8());
            cur.samplerSources.append(tok[2].toUtf8());
        } else if (kw == QLatin1String("endpass")) {
            inPass = false;
            if (!cur.vert.isEmpty()) {
                m_ops.append(cur);
                m_passCount++;
            }
        } else if (kw.size() >= 3 && kw.at(0) == QLatin1Char('u')) {
            int n = 0;
            if (kw == QLatin1String("u1f")) n = 1;
            else if (kw == QLatin1String("u2f")) n = 2;
            else if (kw == QLatin1String("u3f")) n = 3;
            else if (kw == QLatin1String("u4f")) n = 4;
            else if (kw == QLatin1String("umat4")) n = 16;
            if (n && tok.size() >= 2 + n) {
                Uniform u;
                u.count = n;
                for (int i = 0; i < n; i++) {
                    if (tok[2 + i] == QLatin1String("@TIME@"))
                        u.timeMarker = true;
                    else
                        u.v[i] = tok[2 + i].toFloat();
                }
                cur.uniformNames.append(tok[1].toUtf8());
                cur.uniforms.append(u);
            }
        }
    }

    if (m_ops.isEmpty()) {
        if (error)
            *error = QStringLiteral("el plan no contiene pases");
        return false;
    }
    // Un plan generado antes de existir las marcas `object` no las trae. Sin
    // esto su contenido no llegaria nunca a la escena y saldria todo negro.
    m_hasObjectMarks = std::any_of(m_ops.cbegin(), m_ops.cend(),
                                   [](const Op &o) { return o.kind == Op::BeginObject; });
    return true;
}

// ── resolucion ──────────────────────────────────────────────────────────────

qsizetype GlExecutor::targetIndex(const QString &name)
{
    // Targets incorporados de WE: no son buffers del efecto, son nombres
    // reservados para "el fotograma compuesto hasta ahora". Crearlos como
    // buffers nuevos los dejaba vacios para siempre, y cualquier capa que los
    // muestreara (las de composicion completa) leia transparente.
    if (name == QLatin1String("_rt_FullFrameBuffer")
        || name == QLatin1String("_rt_MipMappedFrameBuffer"))
        return kScene;

    const auto it = m_targetByName.constFind(name);
    if (it != m_targetByName.constEnd())
        return it.value();

    const int div = divisorFromName(name);
    Target t;
    t.w = qMax(1, m_canvasW / div);
    t.h = qMax(1, m_canvasH / div);
    makeTarget(&t.tex, &t.fbo, t.w, t.h);

    const qsizetype idx = m_targets.size();
    m_targets.append(t);
    m_targetByName.insert(name, idx);
    return idx;
}

bool GlExecutor::buildProgram(Op &op)
{
    const GlName v = compileShader(op.vert, GL_VERTEX_SHADER, &m_log);
    const GlName f = compileShader(op.frag, GL_FRAGMENT_SHADER, &m_log);
    if (!v || !f)
        return false;
    const GlName prog = glCreateProgram();
    glAttachShader(prog, v);
    glAttachShader(prog, f);
    glBindAttribLocation(prog, 0, "a_Position");
    glBindAttribLocation(prog, 1, "a_TexCoord");
    // Las de particula conviven con las del quad: genericparticle.vert no
    // declara `a_TexCoord` y ningun otro shader declara estas, asi que ningun
    // programa ve dos nombres en la misma localizacion.
    glBindAttribLocation(prog, 2, "a_TexCoordVec4");
    glBindAttribLocation(prog, 3, "a_TexCoordC2");
    glBindAttribLocation(prog, 4, "a_Color");
    glBindAttribLocation(prog, 5, "a_TexCoordVec4C1");
    // Los de la cinta (genericropeparticle.vert). Conviven con los de arriba
    // porque cada shader declara solo los suyos: a_PositionVec4 y a_Position
    // nunca estan los dos en el mismo programa.
    glBindAttribLocation(prog, 0, "a_PositionVec4");
    glBindAttribLocation(prog, 6, "a_TexCoordVec4C2");
    glBindAttribLocation(prog, 7, "a_TexCoordVec4C3");
    glBindAttribLocation(prog, 8, "a_TexCoordC4");
    glLinkProgram(prog);
    GLint ok = 0;
    glGetProgramiv(prog, GL_LINK_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetProgramiv(prog, GL_INFO_LOG_LENGTH, &len);
        QByteArray buf(qMax(len, 1), '\0');
        glGetProgramInfoLog(prog, buf.size(), nullptr, buf.data());
        m_log += QStringLiteral("link: %1\n").arg(QString::fromUtf8(buf));
        glDeleteProgram(prog);
        return false;
    }
    glDeleteShader(v);
    glDeleteShader(f);
    op.program = prog;
    return true;
}

void GlExecutor::resolve(Op &op)
{
    op.targetIndex = (op.targetName.isEmpty() || op.targetName == QLatin1String("SCREEN"))
                         ? kCompo
                         : targetIndex(op.targetName);

    op.samplers.reserve(op.samplerNames.size());
    for (qsizetype i = 0; i < op.samplerNames.size(); i++) {
        const QByteArray &src = op.samplerSources.at(i);
        Sampler s;
        s.unit = int(i);
        s.location = glGetUniformLocation(op.program, op.samplerNames.at(i).constData());
        if (s.location < 0)
            continue;                       // el shader no lo declara: fuera
        if (src.startsWith("tex:")) {
            s.source = Source::Texture;
            // constFind evita copiar el TexSpec entero solo para leer el id, y
            // permite distinguir "textura ausente" de "id 0".
            const auto it = m_textures.constFind(src.mid(4).toInt());
            if (it == m_textures.constEnd()) {
                m_log += QStringLiteral("sampler sin textura: %1\n")
                             .arg(QString::fromUtf8(src));
                continue;
            }
            s.texture = it->id;
        } else if (src.startsWith("rt:")) {
            s.source = Source::Target;
            s.targetIndex = targetIndex(QString::fromUtf8(src.mid(3)));
        } else {
            s.source = Source::Previous;
        }
        op.samplers.append(s);
    }

    // Podar los uniforms que el programa no declara. El generador del plan
    // emite un juego fijo por pase (g_Color4, g_Brightness, g_Screen...) y la
    // mayoria no existe en cada shader; sin podar, el bucle de dibujado paga
    // una consulta por cada uno y por fotograma.
    QVector<Uniform> live;
    live.reserve(op.uniforms.size());
    for (qsizetype i = 0; i < op.uniforms.size(); i++) {
        Uniform u = op.uniforms.at(i);
        u.location = glGetUniformLocation(op.program, op.uniformNames.at(i).constData());
        if (u.location < 0) {
            m_droppedUniforms++;
            continue;
        }
        live.append(u);
    }
    m_liveUniforms += live.size();
    op.uniforms = live;

    // Traza de resolucion: fuera del bucle de dibujado, se emite una sola vez
    // al cargar el plan. Sirve para ver a que buffer y con que tamano acaba
    // cada pase, que es lo que decide el viewport.
    {
        const Target &t = resolveTarget(op.targetIndex);
        qInfo("  pase %2lld -> %-28s %dx%d  samplers=%lld uniforms=%lld",
              (long long)m_passCount, qPrintable(op.targetName.isEmpty()
                  ? QStringLiteral("(compuesto del objeto)") : op.targetName),
              t.w, t.h, (long long)op.samplers.size(), (long long)op.uniforms.size());
    }

    // Ya no hacen falta las cadenas.
    // Asignar un contenedor vacio libera la memoria; clear() conserva la
    // capacidad reservada, que aqui ya no sirve para nada.
    op.samplerNames = {};
    op.samplerSources = {};
    op.uniformNames = {};
    // El nombre corto sobrevive solo para WE_TRACE_PASES; son 54 cadenas
    // cortas y sirven para casar pase a pase con la traza de glexec.
    op.etiqueta = QStringLiteral("%1 -> %2")
                      .arg(op.frag.section(QLatin1Char('/'), -1),
                           op.targetName.isEmpty() ? QStringLiteral("SCREEN")
                                                   : op.targetName);
    op.vert = {};
    op.frag = {};
    op.targetName = {};
}

bool GlExecutor::buildCompositeProgram()
{
    // Componer con mezcla exige dibujar; glBlitFramebuffer no mezcla. Es el
    // unico shader que el motor lleva dentro: el resto vienen del plan.
    // El vertice aplica la colocacion del objeto con la misma convencion de
    // vector-fila que los shaders del plan (v * M, subida con GL_FALSE).
    static const char *vs =
        "#version 330 core\n"
        "in vec3 a_Position; in vec2 a_TexCoord; out vec2 uv;\n"
        "uniform mat4 mvp;\n"
        "void main(){ uv = a_TexCoord; gl_Position = vec4(a_Position, 1.0) * mvp; }\n";
    static const char *fs =
        "#version 330 core\n"
        "in vec2 uv; out vec4 fragColor; uniform sampler2D src;\n"
        "void main(){ fragColor = texture(src, uv); }\n";

    auto build = [](const char *code, GLenum stage) {
        const GlName sh = glCreateShader(stage);
        glShaderSource(sh, 1, &code, nullptr);
        glCompileShader(sh);
        return sh;
    };
    const GlName v = build(vs, GL_VERTEX_SHADER);
    const GlName f = build(fs, GL_FRAGMENT_SHADER);
    m_composite = glCreateProgram();
    glAttachShader(m_composite, v);
    glAttachShader(m_composite, f);
    glBindAttribLocation(m_composite, 0, "a_Position");
    glBindAttribLocation(m_composite, 1, "a_TexCoord");
    glLinkProgram(m_composite);
    GLint ok = 0;
    glGetProgramiv(m_composite, GL_LINK_STATUS, &ok);
    glDeleteShader(v);
    glDeleteShader(f);
    if (!ok) {
        m_log += QStringLiteral("no se pudo enlazar el shader de composicion\n");
        glDeleteProgram(m_composite);
        m_composite = 0;
        return false;
    }
    m_compositeMvp = glGetUniformLocation(m_composite, "mvp");
    return true;
}

const GlExecutor::Target &GlExecutor::resolveTarget(qsizetype index) const
{
    if (index == kScene)
        return m_scene;
    if (index == kCompo)
        return m_compo[m_compoCur];
    return m_targets.at(index);
}

void GlExecutor::beginObject()
{
    flushObjectToScene();
    if (m_frame < qgetenv("WE_TRACE_FRAMES").toInt()) {
        QByteArray px(qsizetype(m_scene.w) * m_scene.h * 4, '\0');
        glBindFramebuffer(GL_READ_FRAMEBUFFER, m_scene.fbo);
        glReadPixels(0, 0, m_scene.w, m_scene.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
        double rgb = 0;
        const auto *p = reinterpret_cast<const unsigned char *>(px.constData());
        for (qsizetype i = 0; i < px.size(); i += 4)
            rgb += p[i] + p[i + 1] + p[i + 2];
        qInfo("SceneView:    obj %d f=%d escena=rgb=%.2f", m_objeto++, m_frame,
              rgb / (0.75 * px.size()));
    }
    m_objectOpen = true;
    // Cada objeto arranca transparente y aporta solo lo suyo; la mezcla con lo
    // que hay detras ocurre una vez, al componerlo sobre la escena. Antes se
    // copiaba la escena dentro del objeto y se recomponia entera: en Jeanne,
    // donde los nueve objetos declaran `copybackground`, eso mezclaba el fondo
    // nueve veces. Los efectos que necesitan el fondo lo leen del buffer de
    // escena por su nombre (_rt_FullFrameBuffer).
    glClearColor(0, 0, 0, 0);
    for (const Target &t : m_compo) {
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, t.fbo);
        glClear(GL_COLOR_BUFFER_BIT);
    }
}

void GlExecutor::flushObjectToScene()
{
    if (!m_objectOpen || !m_composite)
        return;
    m_objectOpen = false;
    if (m_soloBuffer)
        return;          // su resultado ya se copio a su buffer con nombre
    glBindFramebuffer(GL_FRAMEBUFFER, m_scene.fbo);
    glViewport(0, 0, m_scene.w, m_scene.h);
    glUseProgram(m_composite);
    glEnable(GL_BLEND);
    // Los `Premul*` no vuelven a multiplicar por el alfa: el buffer de un
    // sistema de particulas ya lo trae aplicado, y hacerlo otra vez apaga los
    // halos, que es donde vive casi todo el brillo de una particula.
    switch (m_compose) {
    case Compose::Additive:   glBlendFunc(GL_SRC_ALPHA, GL_ONE); break;
    case Compose::PremulAdd:  glBlendFunc(GL_ONE, GL_ONE); break;
    case Compose::PremulOver: glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA); break;
    case Compose::Normal:
        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                            GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        break;
    }
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, m_compo[m_compoCur].tex);
    glUniform1i(glGetUniformLocation(m_composite, "src"), 0);
    glUniformMatrix4fv(m_compositeMvp, 1, GL_FALSE, m_placement);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
}

bool GlExecutor::initialize(QString *error)
{
    if (m_ready)
        return true;

    // Este trabajo es sincrono y corre en el hilo de render: subir los assets
    // y compilar los programas retrasa el primer fotograma. Se mide para saber
    // cuanto cuesta y decidir si merece hacerlo asincrono.
    QElapsedTimer timer;
    timer.start();

    // Quad en NDC con UV 0..1. Todos los pases son fullscreen.
    static const float verts[] = {
        -1, -1, 0, 0, 0,
         1, -1, 0, 1, 0,
        -1,  1, 0, 0, 1,
         1,  1, 0, 1, 1,
    };
    glGenVertexArrays(1, &m_vao);
    glBindVertexArray(m_vao);
    glGenBuffers(1, &m_vbo);
    glBindBuffer(GL_ARRAY_BUFFER, m_vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof verts, verts, GL_STATIC_DRAW);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 5 * sizeof(float), nullptr);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 5 * sizeof(float),
                          reinterpret_cast<void *>(3 * sizeof(float)));
    glEnableVertexAttribArray(1);

    // Mallas puppet. Mismo layout que el quad (vec3 posicion + vec2 UV), asi
    // que comparten las localizaciones de atributo y los shaders no cambian.
    for (auto it = m_meshes.begin(); it != m_meshes.end(); ++it) {
        MeshSpec &m = it.value();
        const QByteArray data = readAll(m.path);
        const qsizetype vbytes = qsizetype(m.vertexCount) * 5 * sizeof(float);
        const qsizetype ibytes = qsizetype(m.indexCount) * sizeof(unsigned short);
        if (data.size() < vbytes + ibytes) {
            m_log += QStringLiteral("malla corta: %1\n").arg(m.path);
            m.indexCount = 0;   // se dibujara el quad
            continue;
        }

        // Bloque de animacion, si el plan lo anuncio. Se copia a memoria propia
        // porque hay que deformar cada fotograma; si no cuadra el tamano se
        // desactiva la animacion y la malla se queda en reposo, que sigue
        // dibujandose bien.
        if (m.animated()) {
            const qsizetype nv = m.vertexCount, nb = m.boneCount, nk = m.keyCount;
            const qsizetype idxB = nv * 4 * sizeof(quint16);
            const qsizetype wB = nv * 4 * sizeof(float);
            const qsizetype matB = nk * nb * 12 * sizeof(float);
            const char *src = data.constData() + vbytes + ibytes;
            if (data.size() < vbytes + ibytes + idxB + wB + matB) {
                m_log += QStringLiteral("malla sin bloque de animacion completo: %1\n")
                             .arg(m.path);
                m.boneCount = 0;
            } else {
                m.bind.resize(nv * 5);
                memcpy(m.bind.data(), data.constData(), vbytes);
                m.skinned = m.bind;
                m.boneIdx.resize(nv * 4);
                memcpy(m.boneIdx.data(), src, idxB);            src += idxB;
                m.weights.resize(nv * 4);
                memcpy(m.weights.data(), src, wB);              src += wB;
                m.mats.resize(nk * nb * 12);
                memcpy(m.mats.data(), src, matB);
                ++m_meshAnimCount;
            }
        }

        glGenVertexArrays(1, &m.vao);
        glBindVertexArray(m.vao);
        glGenBuffers(1, &m.vbo);
        glBindBuffer(GL_ARRAY_BUFFER, m.vbo);
        glBufferData(GL_ARRAY_BUFFER, vbytes, data.constData(),
                     m.animated() ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 5 * sizeof(float), nullptr);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 5 * sizeof(float),
                              reinterpret_cast<void *>(3 * sizeof(float)));
        glEnableVertexAttribArray(1);
        // El IBO queda registrado en este VAO: basta con enlazar el VAO para
        // dibujar, sin volver a tocar GL_ELEMENT_ARRAY_BUFFER.
        glGenBuffers(1, &m.ibo);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, m.ibo);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, ibytes,
                     data.constData() + vbytes, GL_STATIC_DRAW);
        ++m_meshCount;
    }
    glBindVertexArray(m_vao);
    for (const Op &op : m_ops)
        if (op.kind == Op::Pass && op.mesh >= 0)
            ++m_meshPassCount;

    // Sistemas de particulas. El VBO nace vacio y se redimensiona en el primer
    // fotograma que necesite mas: el numero de particulas vivas sube y baja.
    for (auto it = m_psys.begin(); it != m_psys.end(); ++it) {
        PsysSpec &p = it.value();
        int desconocidas = 0;
        p.sys = we_psys_load(p.path.toLocal8Bit().constData(), &desconocidas);
        if (!p.sys) {
            m_log += QStringLiteral("sistema de particulas no abre: %1\n").arg(p.path);
            continue;
        }
        m_psysUnknownParts += desconocidas;
        glGenVertexArrays(1, &p.vao);
        glBindVertexArray(p.vao);
        glGenBuffers(1, &p.vbo);
        glBindBuffer(GL_ARRAY_BUFFER, p.vbo);
        // Dos layouts, uno por shader; ver weparticles.h. El sistema dice cual.
        struct Attr { int loc, n, off; };
        static const Attr sprite[] = {
            {0, 3, 0}, {2, 4, 3}, {3, 2, 7}, {4, 4, 9}, {5, 4, 13},
        };
        static const Attr cinta[] = {
            {0, 4, 0}, {2, 4, 4}, {4, 4, 8}, {5, 4, 12}, {6, 4, 16}, {7, 4, 20},
            {8, 2, 24},
        };
        const bool esCinta = we_psys_cinta(p.sys) != 0;
        const GLsizei paso = we_psys_floats_por_vertice(p.sys) * sizeof(float);
        const Attr *attr = esCinta ? cinta : sprite;
        const int n_attr = esCinta ? int(std::size(cinta)) : int(std::size(sprite));
        for (int i = 0; i < n_attr; ++i) {
            glVertexAttribPointer(attr[i].loc, attr[i].n, GL_FLOAT, GL_FALSE, paso,
                                  reinterpret_cast<void *>(size_t(attr[i].off) * sizeof(float)));
            glEnableVertexAttribArray(attr[i].loc);
        }
        ++m_psysCount;
    }
    glBindVertexArray(m_vao);

    for (auto it = m_textures.begin(); it != m_textures.end(); ++it) {
        TexSpec &t = it.value();
        const QByteArray data = readAll(t.path);
        if (data.size() < qsizetype(t.w) * t.h * 4) {
            m_log += QStringLiteral("textura corta: %1\n").arg(t.path);
            continue;
        }
        glGenTextures(1, &t.id);
        glBindTexture(GL_TEXTURE_2D, t.id);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, t.w, t.h, 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, data.constData());
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
        glGenerateMipmap(GL_TEXTURE_2D);
    }

    for (Target &t : m_compo) {
        t.w = m_canvasW;
        t.h = m_canvasH;
        makeTarget(&t.tex, &t.fbo, t.w, t.h);
    }
    m_scene.w = m_canvasW;
    m_scene.h = m_canvasH;
    makeTarget(&m_scene.tex, &m_scene.fbo, m_scene.w, m_scene.h);
    buildCompositeProgram();

    // Compilar y resolver aqui, no en el primer render: asi el coste no cae
    // sobre un fotograma en mitad de la animacion.
    for (Op &op : m_ops) {
        if (op.kind == Op::BeginObject)
            continue;
        if (op.kind == Op::Copy) {
            op.copySrc = op.copySrcName == QLatin1String("prev")
                             ? kCompo : targetIndex(op.copySrcName);
            op.copyDst = op.copyDstName == QLatin1String("prev")
                             ? kCompo : targetIndex(op.copyDstName);
            op.copySrcName.clear();
            op.copyDstName.clear();
            continue;
        }
        if (buildProgram(op))
            resolve(op);
    }

    m_initMs = int(timer.elapsed());
    if (!m_log.isEmpty() && error)
        *error = m_log;
    m_ready = true;
    return true;
}

// ── dibujado ────────────────────────────────────────────────────────────────

void GlExecutor::skinMeshes(float time)
{
    for (auto it = m_meshes.begin(); it != m_meshes.end(); ++it) {
        MeshSpec &m = it.value();
        if (!m.animated() || m.vbo == 0)
            continue;

        // La ultima clave repite la primera para cerrar el bucle, asi que el
        // periodo son keyCount-1 intervalos. Entre clave y clave se
        // interpola: a 13 claves por segundo, saltar a la mas cercana se ve
        // escalonado.
        const int span = m.keyCount - 1;
        const float dur = m.duration > 1e-6f ? m.duration : 1e-6f;
        double fase = std::fmod(double(time) / dur, 1.0);
        if (fase < 0.0)
            fase += 1.0;
        const double fk = fase * span;
        int k0 = int(fk);
        if (k0 >= span)
            k0 = span - 1;
        const float fr = float(fk - k0);

        // Las matrices llegan del plan ya resueltas, 12 floats por hueso por
        // filas (la columna que falta es (0,0,0,1)); aqui solo queda
        // interpolarlas y hacer la suma ponderada: v' = suma_j w_j * (v * M_j).
        const float *m0 = m.mats.constData() + qsizetype(k0) * m.boneCount * 12;
        const float *m1 = m0 + qsizetype(m.boneCount) * 12;   // k0+1 cabe
        QVarLengthArray<float, 12 * 8> blended(m.boneCount * 12);
        for (qsizetype i = 0; i < blended.size(); ++i)
            blended[i] = m0[i] + (m1[i] - m0[i]) * fr;
        const float *mats = blended.constData();
        for (int v = 0; v < m.vertexCount; ++v) {
            const float *p = m.bind.constData() + qsizetype(v) * 5;
            float acc[3] = {0.0f, 0.0f, 0.0f};
            for (int s = 0; s < 4; ++s) {
                const float w = m.weights.at(qsizetype(v) * 4 + s);
                if (w == 0.0f)
                    continue;
                const int j = m.boneIdx.at(qsizetype(v) * 4 + s);
                if (j < 0 || j >= m.boneCount)
                    continue;
                const float *o = mats + qsizetype(j) * 12;
                for (int c = 0; c < 3; ++c)
                    acc[c] += w * (p[0] * o[0 * 3 + c] + p[1] * o[1 * 3 + c]
                                   + p[2] * o[2 * 3 + c] + o[3 * 3 + c]);
            }
            float *d = m.skinned.data() + qsizetype(v) * 5;
            d[0] = acc[0];
            d[1] = acc[1];
            d[2] = acc[2];
            // Las UV no cambian; ya estan copiadas de la pose de reposo.
        }

        glBindBuffer(GL_ARRAY_BUFFER, m.vbo);
        glBufferSubData(GL_ARRAY_BUFFER, 0,
                        qsizetype(m.vertexCount) * 5 * sizeof(float),
                        m.skinned.constData());
    }
}

void GlExecutor::setFit(int encaje, float zoom, float despX, float despY)
{
    // Se acota aqui y no en quien llama: los valores vienen de la config del
    // plugin, o sea de un fichero que el usuario puede editar a mano. Un zoom
    // de cero seria una division por cero en el reparto del recorte.
    m_fit = (encaje >= Cubrir && encaje <= Estirar) ? encaje : int(Cubrir);
    m_zoom = qBound(0.25f, zoom, 8.0f);
    m_despX = qBound(-1.0f, despX, 1.0f);
    m_despY = qBound(-1.0f, despY, 1.0f);
}

void GlExecutor::setBarColor(float r, float g, float b)
{
    m_bar[0] = qBound(0.0f, r, 1.0f);
    m_bar[1] = qBound(0.0f, g, 1.0f);
    m_bar[2] = qBound(0.0f, b, 1.0f);
}

void GlExecutor::render(GlName targetFbo, int viewW, int viewH, float time)
{
    if (!m_ready)
        return;

    skinMeshes(time);

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_CULL_FACE);
    glDisable(GL_SCISSOR_TEST);
    glBindVertexArray(m_vao);

    // La escena se limpia una vez por fotograma; cada objeto se compone
    // encima. Antes cada objeto limpiaba el unico buffer que habia y borraba
    // al anterior: solo se veia la ultima capa.
    glBindFramebuffer(GL_FRAMEBUFFER, m_scene.fbo);
    glViewport(0, 0, m_scene.w, m_scene.h);
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    m_objectOpen = false;
    if (!m_hasObjectMarks) {
        static const float ident[16] = {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1};
        memcpy(m_placement, ident, sizeof ident);
        m_compose = Compose::Normal;
        beginObject();   // plan antiguo: todo el plan es un solo objeto
    }

    for (const Op &op : m_ops) {
        if (op.kind == Op::BeginObject) {
            // El flush del objeto anterior usa SU colocacion: primero
            // componer, despues adoptar la del que empieza.
            beginObject();
            memcpy(m_placement, op.placement, sizeof m_placement);
            m_compose = op.compose;
            m_soloBuffer = op.soloBuffer;
            continue;
        }
        if (op.kind == Op::Copy) {
            const Target &s = resolveTarget(op.copySrc);
            const Target &d = resolveTarget(op.copyDst);
            glBindFramebuffer(GL_READ_FRAMEBUFFER, s.fbo);
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, d.fbo);
            glBlitFramebuffer(0, 0, s.w, s.h, 0, 0, d.w, d.h,
                              GL_COLOR_BUFFER_BIT, GL_LINEAR);
            continue;
        }
        if (!op.program)
            continue;

        const bool toScreen = op.targetIndex == kCompo;
        const Target &dst = toScreen ? m_compo[m_compoCur ^ 1] : resolveTarget(op.targetIndex);

        glBindFramebuffer(GL_FRAMEBUFFER, dst.fbo);
        glViewport(0, 0, dst.w, dst.h);
        glClear(GL_COLOR_BUFFER_BIT);
        glUseProgram(op.program);

        switch (op.blend) {
        case Blend::None:     glDisable(GL_BLEND); break;
        case Blend::Additive: glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE); break;
        case Blend::Normal:   glEnable(GL_BLEND);
                              glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA); break;
        case Blend::PremulAdditive:
            glEnable(GL_BLEND);
            glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE, GL_ONE, GL_ONE);
            break;
        case Blend::PremulAlpha:
            glEnable(GL_BLEND);
            glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                                GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
            break;
        }

        for (const Sampler &s : op.samplers) {
            GLuint tex = s.texture;
            if (s.source == Source::Target)
                tex = resolveTarget(s.targetIndex).tex;
            else if (s.source == Source::Previous)
                tex = m_compo[m_compoCur].tex;
            glActiveTexture(GL_TEXTURE0 + s.unit);
            glBindTexture(GL_TEXTURE_2D, tex);
            glUniform1i(s.location, s.unit);
        }

        for (const Uniform &u : op.uniforms) {
            // Sin copia: se pasa el puntero a los valores ya parseados. Solo
            // g_Time necesita un valor distinto por fotograma.
            const float *v = u.v;
            if (u.timeMarker)
                v = &time;
            switch (u.count) {
            case 1:  glUniform1fv(u.location, 1, v); break;
            case 2:  glUniform2fv(u.location, 1, v); break;
            case 3:  glUniform3fv(u.location, 1, v); break;
            case 4:  glUniform4fv(u.location, 1, v); break;
            case 16: glUniformMatrix4fv(u.location, 1, GL_FALSE, v); break;
            default: break;
            }
        }

        // Un pase con malla dibuja la geometria puppet; el resto, el quad. La
        // malla se salta si no llego a subirse (fichero corto).
        const MeshSpec *mesh = op.mesh >= 0 ? meshFor(op.mesh) : nullptr;
        if (op.psys >= 0) {
            drawPsys(op.psys, time);
        } else if (mesh) {
            glBindVertexArray(mesh->vao);
            glDrawElements(GL_TRIANGLES, mesh->indexCount, GL_UNSIGNED_SHORT, nullptr);
            glBindVertexArray(m_vao);
        } else {
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        }
        if (m_frame < qgetenv("WE_TRACE_FRAMES").toInt()
            && !qgetenv("WE_TRACE_PASES").isEmpty()) {
            QByteArray px(qsizetype(dst.w) * dst.h * 4, '\0');
            glBindFramebuffer(GL_READ_FRAMEBUFFER, dst.fbo);
            glReadPixels(0, 0, dst.w, dst.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
            double rgb = 0, a = 0;
            const auto *p = reinterpret_cast<const unsigned char *>(px.constData());
            for (qsizetype i = 0; i < px.size(); i += 4) {
                rgb += p[i] + p[i + 1] + p[i + 2];
                a += p[i + 3];
            }
            const double n = double(px.size()) / 4;
            qInfo("SceneView:     pase %-40s =rgb=%.2f a=%.1f",
                  qPrintable(op.etiqueta), rgb / (3 * n), a / n);
        }

        if (toScreen)
            m_compoCur ^= 1;
    }

    flushObjectToScene();

    // Componer sobre el destino de Qt. El lienzo del autor casi nunca tiene la
    // proporcion de la pantalla, asi que aqui se decide que se ve: los tres
    // encajes salen de la misma cuenta cambiando solo como se elige la escala.
    const Target &src = m_scene;
    double sX, sY;                       // pixeles de pantalla por pixel de escena
    switch (m_fit) {
    case Encajar:
        sX = sY = qMin(double(viewW) / src.w, double(viewH) / src.h);
        break;
    case Estirar:
        sX = double(viewW) / src.w;
        sY = double(viewH) / src.h;
        break;
    default:
        sX = sY = qMax(double(viewW) / src.w, double(viewH) / src.h);
        break;
    }
    sX *= m_zoom;
    sY *= m_zoom;

    // Cuanto lienzo cabe en la pantalla. Si sobra escena hay recorte y el
    // desplazamiento elige por donde; si falta, la diferencia son barras. Con
    // `Cubrir` y zoom 1 no hay barras y esto es lo que se hacia antes.
    const int cropW = qBound(1, int(qRound(viewW / sX)), src.w);
    const int cropH = qBound(1, int(qRound(viewH / sY)), src.h);
    // El eje Y del lienzo crece hacia arriba (lo fija la MVP que hornea
    // `object_mvp`), asi que un desplazamiento positivo sube.
    const int x0 = qRound((src.w - cropW) * 0.5 * (1.0 + m_despX));
    const int y0 = qRound((src.h - cropH) * 0.5 * (1.0 + m_despY));
    const int dstW = qMin(viewW, int(qRound(cropW * sX)));
    const int dstH = qMin(viewH, int(qRound(cropH * sY)));
    const int dx = (viewW - dstW) / 2;
    const int dy = (viewH - dstH) / 2;

    // El encaje se cambia desde la configuracion y no deja rastro en ningun
    // sitio: sin esto, "no se ve entera" y "se ve entera pero mal recortada"
    // son el mismo sintoma. Se traza al cambiar, no por fotograma.
    if (const quint64 firma = (quint64(m_fit) << 56) ^ (quint64(cropW) << 40)
                              ^ (quint64(cropH) << 24) ^ (quint64(x0) << 12) ^ quint64(y0)
                              ^ (quint64(dstW) << 4) ^ quint64(dstH);
        firma != m_diagFitSig) {
        m_diagFitSig = firma;
        qInfo("GlExecutor: encaje=%d escena %dx%d -> se ve %dx%d desde (%d,%d) "
              "-> destino %dx%d en (%d,%d) de %dx%d",
              m_fit, src.w, src.h, cropW, cropH, x0, y0, dstW, dstH, dx, dy,
              viewW, viewH);
    }

    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, targetFbo);
    // Las barras se pintan aqui y no se dejan al QML de debajo: Qt limpia su
    // destino a transparente al abrir el pase, pero el item se compone SIN
    // mezcla alfa ---`setAlphaBlending(false)`, que es lo que evita que los
    // bordes de la escena se oscurezcan dos veces---, asi que lo que no
    // pintemos sale negro en vez de dejar ver el fondo.
    if (dstW < viewW || dstH < viewH) {
        glClearColor(m_bar[0], m_bar[1], m_bar[2], 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
    }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, src.fbo);
    glViewport(0, 0, viewW, viewH);
    // El rectangulo de destino lo lleva el propio blit; el viewport de arriba
    // es para dejar el estado como Qt lo espera al volver de endExternal().
    glBlitFramebuffer(x0, y0, x0 + cropW, y0 + cropH,
                      dx, dy, dx + dstW, dy + dstH,
                      GL_COLOR_BUFFER_BIT, GL_LINEAR);
    // Dejar bindeado el destino de Qt, no el framebuffer por defecto: Qt sigue
    // dibujando ahi cuando volvemos de endExternal().
    glBindFramebuffer(GL_FRAMEBUFFER, targetFbo);
    glBindVertexArray(0);

    // Traza de los primeros fotogramas: media RGBA de cada buffer con nombre y
    // del compuesto. WE_TRACE_FRAMES=N la activa. Sirve para los efectos
    // temporales, donde el fallo no esta en un fotograma sino en como
    // evoluciona de uno al siguiente y hacia que punto fijo converge.
    if (const int traza = qgetenv("WE_TRACE_FRAMES").toInt(); m_frame < traza) {
        auto media = [](const Target &t) {
            QByteArray px(qsizetype(t.w) * t.h * 4, '\0');
            glBindFramebuffer(GL_READ_FRAMEBUFFER, t.fbo);
            glReadPixels(0, 0, t.w, t.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
            double rgb = 0, a = 0;
            const auto *p = reinterpret_cast<const unsigned char *>(px.constData());
            for (qsizetype i = 0; i < px.size(); i += 4) {
                rgb += p[i] + p[i + 1] + p[i + 2];
                a += p[i + 3];
            }
            const double n = double(px.size()) / 4;
            return QStringLiteral("rgb=%1 a=%2").arg(rgb / (3 * n), 0, 'f', 2)
                                                .arg(a / n, 0, 'f', 1);
        };
        QString linea = QStringLiteral("compo=%1 escena=%2")
                            .arg(media(m_compo[m_compoCur]), media(m_scene));
        for (auto it = m_targetByName.constBegin(); it != m_targetByName.constEnd(); ++it)
            linea += QStringLiteral("  %1=%2").arg(it.key(), media(m_targets.at(it.value())));
        qInfo("SceneView: t=%.2f f=%d %s", double(time), m_frame, qPrintable(linea));
    }
    ++m_frame;

    // Diagnostico de una sola vez: comparar el compuesto con lo que acaba en
    // el destino de Qt separa "el motor no dibuja" de "el blit no llega".
    if (!m_diagDone) {
        m_diagDone = true;
        m_diagTargets = m_targets.size();
        // Volcado del buffer de escena, para comparar pixel a pixel contra el
        // ejecutor offline sobre el MISMO plan. Se activa con
        // WE_DUMP_SCENE=/ruta.rgba; sin la variable no cuesta nada.
        const QByteArray ruta = qgetenv("WE_DUMP_SCENE");
        if (!ruta.isEmpty()) {
            QByteArray px(qsizetype(src.w) * src.h * 4, '\0');
            glBindFramebuffer(GL_READ_FRAMEBUFFER, src.fbo);
            glReadPixels(0, 0, src.w, src.h, GL_RGBA, GL_UNSIGNED_BYTE, px.data());
            QFile f(QString::fromLocal8Bit(ruta));
            if (f.open(QIODevice::WriteOnly)) {
                f.write(px);
                qInfo("SceneView: escena volcada a %s (%dx%d)",
                      ruta.constData(), src.w, src.h);
            }
        }
        auto muestra = [](GLuint fbo, int x, int y) {
            unsigned char px[16 * 16 * 4] = {};
            glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo);
            glReadPixels(x, y, 16, 16, GL_RGBA, GL_UNSIGNED_BYTE, px);
            long suma = 0;
            for (unsigned char c : px)
                suma += c;
            return double(suma) / sizeof(px);
        };
        // Solo se mide el compuesto propio. Leer del framebuffer de Qt daba
        // resultados que no se correspondian con lo que acababa en pantalla
        // (0.0 en escenas que se veian perfectamente), asi que esa medida se
        // retiro: una medicion que miente es peor que no medir. Ademas
        // glReadPixels es sincrono y frena el pipeline.
        m_diagCompoMean = muestra(src.fbo, src.w / 2, src.h / 2);
        m_diagBlitError = int(glGetError());
    }
}

const GlExecutor::MeshSpec *GlExecutor::meshFor(int id) const
{
    const auto it = m_meshes.constFind(id);
    if (it == m_meshes.constEnd() || it->vao == 0 || it->indexCount <= 0)
        return nullptr;
    return &it.value();
}

bool GlExecutor::drawPsys(int id, float time)
{
    const auto it = m_psys.find(id);
    if (it == m_psys.end() || !it->sys || !it->vao)
        return false;
    PsysSpec &p = it.value();
    const int nv = we_psys_update(p.sys, time);
    if (nv <= 0)
        return false;

    glBindVertexArray(p.vao);
    glBindBuffer(GL_ARRAY_BUFFER, p.vbo);
    const qsizetype bytes = qsizetype(nv)
                          * we_psys_floats_por_vertice(it->sys) * sizeof(float);
    // El numero de particulas vivas sube y baja; se reserva por el maximo visto
    // y a partir de ahi solo se reescribe, sin volver a pedir memoria a GL.
    if (nv > p.capacidad) {
        glBufferData(GL_ARRAY_BUFFER, bytes, we_psys_vertices(p.sys), GL_DYNAMIC_DRAW);
        p.capacidad = nv;
    } else {
        glBufferSubData(GL_ARRAY_BUFFER, 0, bytes, we_psys_vertices(p.sys));
    }
    glDrawArrays(GL_TRIANGLES, 0, nv);
    glBindVertexArray(m_vao);
    return true;
}

void GlExecutor::releaseResources()
{
    if (!m_ready)
        return;
    for (Op &op : m_ops) {
        if (op.program) {
            glDeleteProgram(op.program);
            op.program = 0;
        }
    }
    for (TexSpec &t : m_textures) {
        if (t.id)
            glDeleteTextures(1, &t.id);
        t.id = 0;
    }
    for (Target &t : m_targets) {
        glDeleteTextures(1, &t.tex);
        glDeleteFramebuffers(1, &t.fbo);
    }
    m_targets.clear();
    m_targetByName.clear();
    for (Target &t : m_compo) {
        if (t.tex) glDeleteTextures(1, &t.tex);
        if (t.fbo) glDeleteFramebuffers(1, &t.fbo);
        t = Target();
    }
    if (m_scene.tex) glDeleteTextures(1, &m_scene.tex);
    if (m_scene.fbo) glDeleteFramebuffers(1, &m_scene.fbo);
    m_scene = Target();
    if (m_composite) glDeleteProgram(m_composite);
    m_composite = 0;
    for (MeshSpec &m : m_meshes) {
        if (m.vbo) glDeleteBuffers(1, &m.vbo);
        if (m.ibo) glDeleteBuffers(1, &m.ibo);
        if (m.vao) glDeleteVertexArrays(1, &m.vao);
        m.vao = m.vbo = m.ibo = 0;
    }
    for (PsysSpec &p : m_psys) {
        if (p.vbo) glDeleteBuffers(1, &p.vbo);
        if (p.vao) glDeleteVertexArrays(1, &p.vao);
        p.vao = p.vbo = 0;
        p.capacidad = 0;
        we_psys_free(p.sys);
        p.sys = nullptr;
    }
    m_psysCount = 0;
    if (m_vbo) glDeleteBuffers(1, &m_vbo);
    if (m_vao) glDeleteVertexArrays(1, &m_vao);
    m_vbo = m_vao = 0;
    m_ready = false;
}
