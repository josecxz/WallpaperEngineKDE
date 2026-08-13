/* Simulador de sistemas de particulas de Wallpaper Engine.
 *
 * Se compila TAL CUAL en los dos ejecutores --- `tools/glexec.c` (offline, C) y
 * `src/glexecutor.cpp` (en vivo, C++) --- porque una simulacion escrita dos
 * veces son dos simulaciones distintas en cuanto una de las dos se toca. Por
 * eso no incluye GL ni Qt: produce un array de vertices y quien lo llama decide
 * como subirlo.
 *
 * El reparto con Python es el mismo que en el resto del motor: `weparticles.py`
 * lee el JSON, resuelve nombres y valores por defecto y escribe un fichero
 * `.psys` con numeros; esto solo lo ejecuta. El formato de ese fichero es el
 * contrato entre los dos y esta documentado en `we_psys_load`.
 *
 * Layout del vertice (17 floats), pensado para `shaders/genericparticle.vert`
 * con GS_ENABLED=0, que es la ruta sin geometry shader:
 *
 *   loc 0  a_Position       vec3   centro de la particula
 *   loc 2  a_TexCoordVec4   vec4   (u, v, rotacion z, tamano)
 *   loc 3  a_TexCoordC2     vec2   (rotacion x, rotacion y)
 *   loc 4  a_Color          vec4   color y alfa ya modulados
 *   loc 5  a_TexCoordVec4C1 vec4   (velocidad xyz, vida normalizada)
 *
 * Seis vertices por particula, `GL_TRIANGLES`, sin indices: con 512 particulas
 * como maximo en el corpus el ahorro de un IBO no compensa su complejidad.
 */

#ifndef WE_PARTICLES_H
#define WE_PARTICLES_H

#ifdef __cplusplus
extern "C" {
#endif

#define WE_PSYS_FLOATS_POR_VERTICE 17
#define WE_PSYS_VERTICES_POR_PARTICULA 6

typedef struct WeParticleSystem WeParticleSystem;

/* Carga un `.psys`. Devuelve NULL si no se puede abrir o esta vacio.
 * `id_desconocidas` recibe --- si no es NULL --- cuantas piezas del fichero no
 * se reconocieron: son las que el sistema NO simula, y conviene avisar en vez
 * de dibujar algo silenciosamente incompleto. */
WeParticleSystem *we_psys_load(const char *path, int *piezas_desconocidas);
void we_psys_free(WeParticleSystem *s);

/* Avanza la simulacion hasta el instante `t` (segundos) y reconstruye los
 * vertices. Devuelve cuantos vertices hay que dibujar.
 *
 * `t` es el reloj de la escena, no un delta: el ejecutor offline repite el plan
 * con tiempos crecientes y el motor en vivo pasa su tiempo real. Retroceder en
 * el tiempo reinicia el sistema, que es lo unico razonable. */
int we_psys_update(WeParticleSystem *s, float t);

const float *we_psys_vertices(const WeParticleSystem *s);

#ifdef __cplusplus
}
#endif

#endif
