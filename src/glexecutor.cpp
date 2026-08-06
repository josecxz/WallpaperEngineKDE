// GL_GLEXT_PROTOTYPES debe definirse antes de cualquier include: Qt
// arrastra GL/gl.h, y si llega primero no se declaran los prototipos de GL 2+.
#define GL_GLEXT_PROTOTYPES
#include <GL/gl.h>
#include <GL/glext.h>

#include "glexecutor.h"

#include <QElapsedTimer>
#include <QFile>
#include <QOpenGLContext>

#include <algorithm>
#include <QTextStream>

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
        } else if (kw == QLatin1String("object")) {
            Op op;
            op.kind = Op::BeginObject;
            op.copyBackground = tok.size() >= 2 && tok[1] == QLatin1String("1");
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
        } else if (kw == QLatin1String("blend") && tok.size() >= 2) {
            const QString &b = tok[1];
            cur.blend = (b == QLatin1String("none") || b == QLatin1String("opaque"))
                            ? Blend::None
                            : (b == QLatin1String("additive") ? Blend::Additive : Blend::Normal);
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
    op.vert = {};
    op.frag = {};
    op.targetName = {};
}

bool GlExecutor::buildCompositeProgram()
{
    // Componer con mezcla exige dibujar; glBlitFramebuffer no mezcla. Es el
    // unico shader que el motor lleva dentro: el resto vienen del plan.
    static const char *vs =
        "#version 330 core\n"
        "in vec3 a_Position; in vec2 a_TexCoord; out vec2 uv;\n"
        "void main(){ uv = a_TexCoord; gl_Position = vec4(a_Position, 1.0); }\n";
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
    glBindFramebuffer(GL_FRAMEBUFFER, m_scene.fbo);
    glViewport(0, 0, m_scene.w, m_scene.h);
    glUseProgram(m_composite);
    glEnable(GL_BLEND);
    glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, m_compo[m_compoCur].tex);
    glUniform1i(glGetUniformLocation(m_composite, "src"), 0);
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

void GlExecutor::render(GlName targetFbo, int viewW, int viewH, float time)
{
    if (!m_ready)
        return;

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
    if (!m_hasObjectMarks)
        beginObject();   // plan antiguo: todo el plan es un solo objeto

    for (const Op &op : m_ops) {
        if (op.kind == Op::BeginObject) {
            beginObject();
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

        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        if (toScreen)
            m_compoCur ^= 1;
    }

    flushObjectToScene();

    // Componer sobre el destino de Qt con recorte que preserva la proporcion.
    const Target &src = m_scene;
    const double scale = qMax(double(viewW) / src.w, double(viewH) / src.h);
    const int cropW = qRound(viewW / scale);
    const int cropH = qRound(viewH / scale);
    const int x0 = (src.w - cropW) / 2;
    const int y0 = (src.h - cropH) / 2;

    glBindFramebuffer(GL_READ_FRAMEBUFFER, src.fbo);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, targetFbo);
    glViewport(0, 0, viewW, viewH);
    glBlitFramebuffer(x0, y0, x0 + cropW, y0 + cropH, 0, 0, viewW, viewH,
                      GL_COLOR_BUFFER_BIT, GL_LINEAR);
    // Dejar bindeado el destino de Qt, no el framebuffer por defecto: Qt sigue
    // dibujando ahi cuando volvemos de endExternal().
    glBindFramebuffer(GL_FRAMEBUFFER, targetFbo);
    glBindVertexArray(0);

    // Diagnostico de una sola vez: comparar el compuesto con lo que acaba en
    // el destino de Qt separa "el motor no dibuja" de "el blit no llega".
    if (!m_diagDone) {
        m_diagDone = true;
        m_diagTargets = m_targets.size();
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
    if (m_vbo) glDeleteBuffers(1, &m_vbo);
    if (m_vao) glDeleteVertexArrays(1, &m_vao);
    m_vbo = m_vao = 0;
    m_ready = false;
}
