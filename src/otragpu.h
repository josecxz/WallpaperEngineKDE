// OtraGpu: dibujar el fondo en una GPU que no es la de plasmashell.
//
// En un portatil hibrido plasmashell vive en la integrada, que es la que lleva
// el panel, y el fondo se comia la mitad de ella (NOTAS: "Elegir la GPU que
// renderiza"). La GPU la elige libglvnd por PROCESO al cargar el driver, pero
// el reparto de las llamadas GL es por HILO segun el contexto actual. Asi que,
// sin hilos nuevos ni otro proceso, el mismo hilo de render de Qt puede:
//
//   1. guardar el contexto de Qt y poner uno propio sobre la otra GPU,
//   2. ejecutar el plan ahi, sobre un FBO propio del tamano del item,
//   3. leer el fotograma a memoria y devolverle el contexto a Qt,
//   4. subirlo a una textura de la GPU de Qt y copiarlo a su framebuffer.
//
// El paso 3 va por la CPU porque no hay otro: el GL de NVIDIA no dibuja en un
// dmabuf LINEAR ---ni propio ni ajeno, solo lo muestrea--- y la integrada no
// sabe leer su formato en bloques. Medido a 2560x1440: ~1,2 ms leer en la
// dedicada y ~2 ms subir en la integrada. Ver NOTAS, la sonda del dmabuf.
//
// Se ejecuta el plan con el mismo contexto que `tools/glexec.c` (GL 3.3
// core): en vivo y offline lo corre ahora el mismo tipo de contexto.

#pragma once

#include <QByteArray>
#include <QString>

class OtraGpu
{
public:
    OtraGpu() = default;
    OtraGpu(const OtraGpu &) = delete;
    OtraGpu &operator=(const OtraGpu &) = delete;

    // Busca un dispositivo EGL con GPU de verdad cuyo renderer no sea el de
    // Qt y crea un contexto en el. Con el contexto de Qt ACTIVO, que es el
    // que se compara y el que se devuelve. false si no hay otra GPU o si Qt no
    // usa EGL: entonces se dibuja en la de Qt, como siempre. Si se llama o no
    // lo decide la configuracion (`DedicatedGpu`, `wectl gpu`), no esta clase.
    // `informe` dice que se eligio, o por que no.
    bool abrir(QString *informe);
    bool abierta() const { return m_ctx != nullptr; }

    // Pone el contexto propio y recuerda el que habia, con su API de EGL.
    bool entrar();
    // Devuelve el que habia. Llamarlo siempre tras un `entrar()` con exito.
    void salir();

    // Dentro: el FBO propio de w x h sobre el que dibuja el plan. Se rehace
    // si el item cambia de tamano.
    unsigned destino(int w, int h);
    // Dentro: deja en memoria el fotograma que `presentar` va a subir.
    //
    // Sincrono (`asincrono = false`), lee el que se acaba de dibujar y espera
    // a la GPU para ello: ~3 ms a 1920x1200, la mayor parte del coste de CPU
    // del fondo. Asincrono, encarga la lectura de este a un PBO con una valla
    // y entrega el ANTERIOR, que ya esta en memoria: la CPU no espera a nadie
    // y el precio es un fotograma de retraso. Los PBO van mapeados de forma
    // persistente (ARB_buffer_storage), asi que la integrada sube directamente
    // desde donde los dejo la dedicada, sin otra copia de 9 MB por medio. Sin
    // esa extension, siempre sincrono.
    void leer(bool asincrono);
    // Fuera, con el contexto de Qt: sube el fotograma y lo copia sobre
    // `qtFbo`, dejandolo bindeado como lo espera Qt.
    void presentar(unsigned qtFbo);

    // Libera lo propio de la otra GPU. Dentro.
    void liberarDentro();
    // Libera la textura de la GPU de Qt, si su contexto es el actual, y el
    // contexto propio. Fuera, al final.
    void cerrar();

    // Milisegundos de CPU de los dos pasos de copia, media movil.
    double msLeer() const { return m_msLeer; }
    double msPresentar() const { return m_msPresentar; }
    // Suma de los dos pasos y numero de copias desde la ultima llamada; las
    // pone a cero. Para `WE_MEDIDAS`.
    void tomarMuestrasCopia(double &leer, double &presentar, int &n)
    {
        leer = m_sumaLeer; presentar = m_sumaPresentar; n = m_nCopias;
        m_sumaLeer = m_sumaPresentar = 0; m_nCopias = 0;
    }

private:
    // Tipos de EGL como `void *` para no meter EGL ---y lo que arrastra--- en
    // las cabeceras que ve Qt.
    void *m_dpy = nullptr, *m_ctx = nullptr;
    void *m_prevDpy = nullptr, *m_prevDraw = nullptr, *m_prevRead = nullptr,
         *m_prevCtx = nullptr;
    unsigned m_prevApi = 0;
    void *m_ctxQt = nullptr;     // el de Qt que se vio al abrir

    // En la otra GPU.
    unsigned m_tex = 0, m_fbo = 0;
    // En la de Qt.
    unsigned m_texQt = 0, m_fboQt = 0;
    int m_w = 0, m_h = 0;        // del FBO propio
    int m_wQt = 0, m_hQt = 0;    // de la textura de Qt
    QByteArray m_pixeles;
    // De donde sube `presentar`: `m_pixeles` o un PBO mapeado.
    const void *m_fuente = nullptr;
    // Anillo de dos PBO para la lectura asincrona. `m_valla` son GLsync.
    unsigned m_pbo[2] = {0, 0};
    void *m_mapa[2] = {nullptr, nullptr};
    void *m_valla[2] = {nullptr, nullptr};
    bool m_lleno[2] = {false, false};
    int m_cur = 0;
    int m_persistente = -1;      // -1 sin comprobar; 0 no hay; 1 si
    void crearAnillo();
    void soltarAnillo();

    double m_msLeer = 0.0, m_msPresentar = 0.0;
    double m_sumaLeer = 0.0, m_sumaPresentar = 0.0;
    int m_nCopias = 0;
};
