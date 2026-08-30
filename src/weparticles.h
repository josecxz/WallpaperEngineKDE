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
 *
 * Los renderers de cinta --- `rope` y `ropetrail` --- usan OTRO shader,
 * `genericropeparticle.vert`, y por tanto otro vertice (26 floats). No dibujan
 * un sprite por particula sino un quad por SEGMENTO de la cola, y cada quad
 * lleva sus dos extremos y los dos vecinos que dan la tangente:
 *
 *   loc 0  a_PositionVec4    vec4   (inicio xyz, tamano en el inicio)
 *   loc 2  a_TexCoordVec4    vec4   (fin xyz, cuantos puntos tiene la cola)
 *   loc 4  a_Color           vec4   color y alfa en el inicio
 *   loc 5  a_TexCoordVec4C1  vec4   (control 0 xyz, indice del segmento)
 *   loc 6  a_TexCoordVec4C2  vec4   (control 1 xyz, tamano en el fin)
 *   loc 7  a_TexCoordVec4C3  vec4   color y alfa en el fin
 *   loc 8  a_TexCoordC4      vec2   esquina del quad (u cruza, v recorre)
 *
 * `we_psys_cinta` dice cual de los dos formatos toca ANTES de montar el VAO, y
 * `we_psys_floats_por_vertice` el paso. El resto de la API no cambia.
 */

#ifndef WE_PARTICLES_H
#define WE_PARTICLES_H

#ifdef __cplusplus
extern "C" {
#endif

#define WE_PSYS_FLOATS_POR_VERTICE 17
#define WE_PSYS_FLOATS_CINTA 26
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

/* Cuelga `hijo` de `padre` como `eventspawn`: cada vez que muere una particula
 * del padre, el hijo suelta `rafaga` particulas ahi mismo.
 *
 * Los dos siguen siendo sistemas separados ---cada uno con su material, su
 * pase y su `.psys`--- pero se simulan en tandem: el `we_psys_update` del
 * padre da el paso de los dos y el del hijo solo rehace vertices. Por eso el
 * ejecutor tiene que llamar a esto DESPUES de cargar los dos y ANTES del
 * primer `update`. */
void we_psys_seguir(WeParticleSystem *hijo, WeParticleSystem *padre, int rafaga);

const float *we_psys_vertices(const WeParticleSystem *s);

/* 0 = sprites sueltos, 1 = `rope`, 2 = `ropetrail`. Decide el layout del
 * vertice y, con el, como montar el VAO. */
int we_psys_cinta(const WeParticleSystem *s);
int we_psys_floats_por_vertice(const WeParticleSystem *s);

#ifdef __cplusplus
}
#endif

#endif
