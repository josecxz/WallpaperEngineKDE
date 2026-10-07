/* El temblor de cámara de WE (`camerashake`), COMPARTIDO por los dos
 * ejecutores.
 *
 * Misma regla que `weparticles.c`, `wevideo.c` y `wereloj.c`: lo enlazan
 * `tools/glexec.c` (offline) y `src/glexecutor.cpp` (en vivo). Es una fórmula
 * de seis líneas, pero vive una sola vez para que el offline siga prediciendo
 * lo que hace el escritorio.
 *
 * Quien decide si la escena tiembla y con qué amplitud en píxeles es
 * `tools/werender.py` (`temblor_de_camara`); aquí solo se evalúa la curva.
 */
#ifndef WETEMBLOR_H
#define WETEMBLOR_H

#ifdef __cplusplus
extern "C" {
#endif

/* Cuánto se ha movido la cámara en el segundo `t` de la escena, en fracciones
 * del lienzo y con la y hacia ARRIBA, como el lienzo de WE. `ax` y `ay` son la
 * amplitud ya dividida por el ancho y el alto (la línea `temblor` del plan):
 * el ejecutor no sabe el tamaño del lienzo, solo el de lo que dibuja.
 * `velocidad` y `rugosidad` son los `camerashakespeed` y `camerashakeroughness`
 * de la escena, tal cual.
 *
 * La cámara se mueve y la escena, por tanto, al revés: quien coloque una capa
 * tiene que RESTAR esto. */
void we_temblor(float ax, float ay, float velocidad, float rugosidad, float t,
                float *dx, float *dy);

#ifdef __cplusplus
}
#endif

#endif
