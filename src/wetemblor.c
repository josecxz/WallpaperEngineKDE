#include "wetemblor.h"

#include <math.h>

/* Leído en `wallpaper64.exe`, función 0x140199580, que llama la actualización
 * de la cámara (0x1401891a0) cuando la escena tiene `camerashake`:
 *
 *     s = velocidad² * t
 *     v = (cos s, sin 1,333·s)            la z es sin s, y en una escena
 *                                         ortográfica WE la pone a cero
 *     r = rugosidad³
 *     si r > 0,001 y r != 1:  v = v/|v| * |v|^r
 *     cámara += amplitud * v              el ojo y el centro, los dos
 *
 * Los senos son los de la CRT en float: se hace en float para no separarse de
 * WE en segundos grandes. Con |v| = 0 WE dividiría por cero; aquí se queda en
 * cero, que es el límite de la curva. */
void we_temblor(float ax, float ay, float velocidad, float rugosidad, float t,
                float *dx, float *dy)
{
    const float s = velocidad * velocidad * t;
    float x = cosf(s);
    float y = sinf(s * 1.333f);
    const float r = powf(rugosidad, 3.0f);
    if (r > 0.001f && r != 1.0f) {
        const float n = sqrtf(x * x + y * y);
        if (n > 0.0f) {
            const float f = powf(n, r) / n;
            x *= f;
            y *= f;
        }
    }
    *dx = ax * x;
    *dy = ay * y;
}
