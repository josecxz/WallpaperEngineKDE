/* Sonda de simulacion: carga un `.psys`, lo avanza y resume lo que sale.
 *
 * Existe porque un PNG no sirve para comprobar lo que hace un sistema de
 * particulas. Un operador puede estar equivocado por un factor de diez y la
 * escena verse igual --- la capa es sutil, las particulas caen fuera del lienzo,
 * o las que se ven son de otro sistema. Lo que hay que mirar son las
 * velocidades, y aqui se miran directamente sobre el MISMO simulador que
 * ejecutan los dos ejecutores, sin GL de por medio.
 *
 * Es la herramienta con la que se leyo `remapvalue`: comprobar que la velocidad
 * media de la lluvia de `3597772384` cae en el centro de la caja que declara su
 * JSON, y no un factor por encima o por debajo.
 *
 * Uso:
 *     make psysprobe
 *     obj/psysprobe <fichero.psys> <segundos> [<x> <y> <z> del puntero]
 *
 * Los tres ultimos ponen el raton en coordenadas del SISTEMA ---las mismas en
 * las que salen las posiciones que imprime--- para ver que hacen los puntos de
 * control atados al cursor. Sin ellos no hay raton, que es un estado distinto
 * de tenerlo en el (0,0,0): sin raton, esos operadores no actuan.
 *
 * El `.psys` lo escribe `tools/weparticles.py`; el renderizador offline deja los
 * suyos en su directorio temporal.
 */
#include "weparticles.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "uso: psysprobe <fichero.psys> <segundos>\n");
        return 2;
    }

    int desconocidas = 0;
    WeParticleSystem *s = we_psys_load(argv[1], &desconocidas);
    if (!s) {
        fprintf(stderr, "no se pudo cargar %s\n", argv[1]);
        return 1;
    }

    if (argc >= 6) {
        const float p[3] = {strtof(argv[3], NULL), strtof(argv[4], NULL),
                            strtof(argv[5], NULL)};
        we_psys_puntero(s, p);
        printf("puntero en (%.1f, %.1f, %.1f)%s\n", p[0], p[1], p[2],
               we_psys_cursor(s) ? "" : "  --- este sistema no lo usa");
    }

    int nv = we_psys_update(s, strtof(argv[2], NULL));
    const float *v = we_psys_vertices(s);
    int paso = we_psys_floats_por_vertice(s);
    /* Un vertice por particula basta: los seis del quad comparten centro y
     * velocidad. En las cintas cada quad es un SEGMENTO, asi que el resumen
     * cuenta segmentos y no particulas; se avisa abajo. */
    const int por_particula = WE_PSYS_VERTICES_POR_PARTICULA;

    printf("piezas sin reconocer: %d\n", desconocidas);
    printf("%s: %d vertices, %d %s\n", argv[1], nv, nv / por_particula,
           we_psys_cinta(s) ? "segmentos de cinta" : "particulas");

    /* La velocidad viaja en `a_TexCoordVec4C1` (xyz) y la posicion en
     * `a_Position`; ver el layout en `weparticles.h`. Las cintas usan otro
     * vertice y ahi no hay velocidad que resumir. */
    if (!we_psys_cinta(s) && nv > 0) {
        double sx = 0, sy = 0, rap = 0, rmin = 1e30, rmax = -1e30;
        double cx = 0, cy = 0;
        double x0 = 1e30, x1 = -1e30, y0 = 1e30, y1 = -1e30;
        int n = 0;
        for (int i = 0; i < nv; i += por_particula) {
            const float *w = v + (size_t)i * paso;
            double vx = w[13], vy = w[14], vz = w[15];
            double r = sqrt(vx * vx + vy * vy + vz * vz);
            sx += vx; sy += vy; rap += r;
            cx += w[0]; cy += w[1];
            if (r < rmin) rmin = r;
            if (r > rmax) rmax = r;
            if (w[0] < x0) x0 = w[0];
            if (w[0] > x1) x1 = w[0];
            if (w[1] < y0) y0 = w[1];
            if (w[1] > y1) y1 = w[1];
            n++;
        }
        printf("velocidad media (%.1f, %.1f)   rapidez media %.1f  min %.1f  max %.1f\n",
               sx / n, sy / n, rap / n, rmin, rmax);
        printf("ocupan x [%.0f, %.0f]  y [%.0f, %.0f]\n", x0, x1, y0, y1);
        printf("centro de la nube (%.1f, %.1f)\n", cx / n, cy / n);
    }

    we_psys_free(s);
    return 0;
}
