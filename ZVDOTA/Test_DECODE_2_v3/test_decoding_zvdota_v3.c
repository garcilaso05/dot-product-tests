#include "util.h"

/* =====================================================================================
 * TEST DE DECODE PARA ZVDOTA (parte B)  --  todo dentro de main(), todo en ensamblador
 *
 * CÓMO LEERLO
 *  - Cada test tiene 3 partes:  (1) marcador  (2) vsetvli = configuración  (3) la dot.
 *  - El marcador `li t5, N` aparece en el VCD (señal dbg_inst) como la palabra 0x00N00F13.
 *    Sirve solo para localizar el test en GTKWave:  N=1 -> 00100F13, N=10 -> 00A00F13 ...
 *  - Las palabras `.word 0x........` son instrucciones ya codificadas a mano: la CPU las
 *    ejecuta como cualquier otra. El comentario de la derecha dice qué instrucción es.
 *  - Las listas ::: "t0" del final le dicen al compilador qué registros toca esa línea.
 *  - Las secuencias donde una instrucción depende de la anterior (li t0 + csrc t0) van en
 *    UN solo __asm__, para que el compilador no pueda meter nada entre medias.
 *
 * SEÑALES A VER EN GTKWAVE (id_decode_inst):
 *   dbg_inst, dbg_valid, dbg_instr_type, dbg_unit, dbg_vregfile_we, dbg_use_mask,
 *   dbg_use_old_vd, dbg_dotp_altfmt, dbg_ex_valid, xcpt_illegal_instruction_int, vl_0, vill, altfmt
 * VALORES: dbg_instr_type 397..401 = las 5 dots; dbg_unit 5 = SIMD, 0 = ALU (valor por defecto)
 *
 * CAMBIOS RESPECTO A LA VERSIÓN ANTERIOR (v2):
 *   - mstatus.FS ya no se comprueba en las dots (decisión de supervisión): se eliminan el test 9
 *     (dot entera con FS apagado) y el test 17 (dot de coma flotante con FS apagado), y ya no se enciende FS.
 *   - Numeración nueva (antiguo -> nuevo): 1..8 igual; 10->9, 11->10, 12->11, 13->12, 14->13, 15->14,
 *     16->15, 18->16, 19->17.
 * ===================================================================================== */

int main(void) {

    unsigned long old_mtvec;   /* aquí se guarda el handler de excepciones original del benchmark */

    /* ---------------------------------------------------------------------------------
     * PREPARACIÓN (se ejecuta una sola vez, antes de los tests)
     * --------------------------------------------------------------------------------- */

    /* Guardamos mtvec (la dirección del handler original) para restaurarlo al final. */
    __asm__ volatile ("csrr %0, mtvec" : "=r"(old_mtvec));   // old_mtvec = mtvec actual

    /* Instalamos nuestro propio handler de excepciones, escrito aquí mismo en ensamblador.
     * Los casos ilegales provocan una excepción real; sin este handler el benchmark terminaría
     * en la primera. Este handler salta la instrucción ilegal y sigue con el siguiente test. */
    __asm__ volatile (
        "j 2f\n"               // Flujo normal: salta POR ENCIMA del código del handler (hasta la etiqueta 2)
        ".p2align 2\n"         // El handler debe empezar en una dirección múltiplo de 4 (lo exige mtvec)
        "1:\n"                 // ---- INICIO DEL HANDLER (solo se ejecuta cuando hay una excepción) ----
        "csrr t6, mepc\n"      // t6 = dirección de la instrucción que provocó la excepción
        "addi t6, t6, 4\n"     // t6 = dirección de la SIGUIENTE instrucción (cada una ocupa 4 bytes)
        "csrw mepc, t6\n"      // mepc = t6: así, al volver, se continúa después de la ilegal
        "mret\n"               // vuelve de la excepción (salta a mepc)
        "2:\n"                 // ---- FIN DEL HANDLER ----
        "lla t0, 1b\n"         // t0 = dirección del handler (etiqueta 1, buscando hacia atrás); lla = dirección relativa al PC
        "csrw mtvec, t0\n"     // mtvec = t0: desde ahora, cualquier excepción salta a nuestro handler
        ::: "t0", "t6");

    /* Encendemos la unidad vectorial (VS) en mstatus. (FS ya no hace falta: el decoder no lo comprueba.) */
    __asm__ volatile (
        "li t0, 0x600\n"      // t0 = 0x600 = bits de VS (mstatus.VS son los bits 10:9)
        "csrs mstatus, t0\n"  // csrs = "set bits": pone a 1 esos bits en mstatus (VS = 11, unidad vectorial ENCENDIDA)
        ::: "t0");

    /* ---------------------------------------------------------------------------------
     * TEST 1: vqwdotau en condiciones normales
     * Qué prueba: el camino "feliz": dot entera, SEW 8, todo en orden.
     * Esperado:   instr_type = 397 (VQWDOTAU), unit = 5 (SIMD), vregfile_we = 1, use_old_vd = 1,
     *             use_mask = 0, dotp_altfmt = 0, sin excepción.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 1" ::: "t5");           // Marcador: t5 = 1 -> en el VCD: 0x00100F13 (estamos en el test 1)
    __asm__ volatile (".word 0x000072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu`: elementos de 8 bits, altfmt = 0, vl al máximo (se guarda en t0)
    __asm__ volatile (".word 0x9A2180F7");            // `vqwdotau.vv v1, v2, v3`: producto escalar de enteros SIN signo

    /* ---------------------------------------------------------------------------------
     * TEST 2: vqwdotas con altfmt = 1
     * Qué prueba: que se reconoce vqwdotas (otro funct6) y que el altfmt del vtype llega a dotp_altfmt.
     * Esperado:   instr_type = 398 (VQWDOTAS), unit = 5, vregfile_we = 1, dotp_altfmt = 1, sin excepción.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 2" ::: "t5");           // Marcador: t5 = 2 -> en el VCD: 0x00200F13
    __asm__ volatile (".word 0x100072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu` con altfmt = 1 (bit 28 de la instrucción)
    __asm__ volatile (".word 0x9E2180F7");            // `vqwdotas.vv v1, v2, v3`: producto escalar de enteros CON signo

    /* ---------------------------------------------------------------------------------
     * TEST 3: vfwdota (BF16 -> FP32)
     * Qué prueba: la dot de coma flotante con SEW 16 y altfmt = 1: debe ser legal.
     * Esperado:   instr_type = 399 (VFWDOTA), unit = 5, vregfile_we = 1, dotp_altfmt = 1, sin excepción.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 3" ::: "t5");           // Marcador: t5 = 3 -> en el VCD: 0x00300F13
    __asm__ volatile (".word 0x108072D7" ::: "t0");   // `vsetvli t0, x0, e16, m1, tu, mu` con altfmt = 1: elementos de 16 bits
    __asm__ volatile (".word 0x922190F7");            // `vfwdota.vv v1, v2, v3`: producto escalar BF16 con resultado FP32

    /* ---------------------------------------------------------------------------------
     * TEST 4: vfqwdota (FP8 -> FP32)
     * Qué prueba: la segunda dot de coma flotante, con SEW 8 y altfmt = 0.
     * Esperado:   instr_type = 400 (VFQWDOTA), unit = 5, vregfile_we = 1, dotp_altfmt = 0, sin excepción.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 4" ::: "t5");           // Marcador: t5 = 4 -> en el VCD: 0x00400F13
    __asm__ volatile (".word 0x000072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu`: elementos de 8 bits, altfmt = 0
    __asm__ volatile (".word 0x9A2190F7");            // `vfqwdota.vv v1, v2, v3`: producto escalar FP8 con resultado FP32

    /* ---------------------------------------------------------------------------------
     * TEST 5: vfqwdota.alt
     * Qué prueba: la quinta y última dot, con altfmt = 1. Con los tests 1 a 5 ya se han visto las 5.
     * Esperado:   instr_type = 401 (VFQWDOTA_ALT), unit = 5, vregfile_we = 1, dotp_altfmt = 1, sin excepción.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 5" ::: "t5");           // Marcador: t5 = 5 -> en el VCD: 0x00500F13
    __asm__ volatile (".word 0x100072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu` con altfmt = 1
    __asm__ volatile (".word 0x9E2190F7");            // `vfqwdota.alt.vv v1, v2, v3`: variante alternativa de FP8

    /* ---------------------------------------------------------------------------------
     * TEST 6: vqwdotau con SEW 16
     * Qué prueba: que la dot entera también acepta SEW 16 (el test 1 solo probó SEW 8).
     * Esperado:   instr_type = 397, unit = 5, vregfile_we = 1, dotp_altfmt = 0, sin excepción.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 6" ::: "t5");           // Marcador: t5 = 6 -> en el VCD: 0x00600F13
    __asm__ volatile (".word 0x008072D7" ::: "t0");   // `vsetvli t0, x0, e16, m1, tu, mu`: elementos de 16 bits, altfmt = 0
    __asm__ volatile (".word 0x9A2180F7");            // `vqwdotau.vv v1, v2, v3`

    /* ---------------------------------------------------------------------------------
     * TEST 7: vqwdotau CON máscara
     * Qué prueba: que el decoder interpreta bien el bit vm (bit 25). vm = 0 significa "usa la máscara v0".
     * Esperado:   instr_type = 397, unit = 5, vregfile_we = 1, use_mask = 1 (en los tests anteriores era 0).
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 7" ::: "t5");           // Marcador: t5 = 7 -> en el VCD: 0x00700F13
    __asm__ volatile (".word 0x000072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu`
    __asm__ volatile (".word 0x982180F7");            // `vqwdotau.vv v1, v2, v3, v0.t`: igual que el test 1 pero con vm = 0 (con máscara)

    /* ---------------------------------------------------------------------------------
     * TEST 8: vl = 0 (cero elementos)
     * Qué prueba: que una dot con 0 elementos sigue siendo legal pero NO escribe nada (no-op).
     * Esperado:   vl_0 = 1, instr_type = 397, unit = 5, vregfile_we = 0 (¡cero!), sin excepción.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 8" ::: "t5");           // Marcador: t5 = 8 -> en el VCD: 0x00800F13
    __asm__ volatile (
        "li t1, 0\n"                                  // t1 = 0: el número de elementos que vamos a pedir
        ".word 0x000372D7\n"                          // `vsetvli t0, t1, e8, m1, tu, mu`: pide AVL = t1 = 0 elementos -> vl = 0
        ::: "t0", "t1");
    __asm__ volatile (".word 0x9A2180F7");            // `vqwdotau.vv v1, v2, v3`: con vl = 0 no debe escribir el destino

    /* ---------------------------------------------------------------------------------
     * TEST 9: vd igual que vs1  (ILEGAL)
     * Qué prueba: la regla "el registro destino no puede coincidir con una fuente" (caso vs1).
     * Esperado:   xcpt_illegal_instruction_int = 1, dbg_ex_valid = 1, instr_type = 0, unit = 0, vregfile_we = 0.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 9" ::: "t5");          // Marcador: t5 = 9 -> en el VCD: 0x00900F13
    __asm__ volatile (".word 0x000072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu`
    __asm__ volatile (".word 0x9A2181F7");            // `vqwdotau.vv v3, v2, v3`: vd = v3 y vs1 = v3 -> ILEGAL

    /* ---------------------------------------------------------------------------------
     * TEST 10: vd igual que vs2  (ILEGAL)
     * Qué prueba: la otra mitad de la misma regla (caso vs2).
     * Esperado:   igual que el test 10: excepción de instrucción ilegal y valores por defecto.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 10" ::: "t5");          // Marcador: t5 = 10 -> en el VCD: 0x00A00F13
    __asm__ volatile (".word 0x000072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu`
    __asm__ volatile (".word 0x9A218177");            // `vqwdotau.vv v2, v2, v3`: vd = v2 y vs2 = v2 -> ILEGAL

    /* ---------------------------------------------------------------------------------
     * TEST 11: encoding que no existe bajo el opcode 0x77  (ILEGAL)
     * Qué prueba: el `default` del case: cualquier pareja funct6/funct3 que no esté en la tabla es ilegal.
     * Esperado:   excepción de instrucción ilegal y valores por defecto.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 11" ::: "t5");          // Marcador: t5 = 11 -> en el VCD: 0x00B00F13
    __asm__ volatile (".word 0x000072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu`
    __asm__ volatile (".word 0x922180F7");            // Parece una dot (opcode 0x77) pero es funct6 de vfwdota con funct3 entero: no existe -> ILEGAL

    /* ---------------------------------------------------------------------------------
     * TEST 12: vqwdotau con SEW 32  (ILEGAL)
     * Qué prueba: que la dot entera rechaza un SEW que no sea 8 ni 16.
     * Esperado:   excepción de instrucción ilegal y valores por defecto.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 12" ::: "t5");          // Marcador: t5 = 12 -> en el VCD: 0x00C00F13
    __asm__ volatile (".word 0x010072D7" ::: "t0");   // `vsetvli t0, x0, e32, m1, tu, mu`: elementos de 32 bits
    __asm__ volatile (".word 0x9A2180F7");            // `vqwdotau.vv v1, v2, v3`: con SEW 32 -> ILEGAL

    /* ---------------------------------------------------------------------------------
     * TEST 13: vfwdota con altfmt = 0  (ILEGAL)
     * Qué prueba: que vfwdota exige altfmt = 1 (el test 3 era igual pero con altfmt = 1 y era legal).
     * Esperado:   excepción de instrucción ilegal y valores por defecto.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 13" ::: "t5");          // Marcador: t5 = 13 -> en el VCD: 0x00D00F13
    __asm__ volatile (".word 0x008072D7" ::: "t0");   // `vsetvli t0, x0, e16, m1, tu, mu` con altfmt = 0
    __asm__ volatile (".word 0x922190F7");            // `vfwdota.vv v1, v2, v3`: SEW 16 correcto pero altfmt = 0 -> ILEGAL

    /* ---------------------------------------------------------------------------------
     * TEST 14: vfwdota con SEW 8  (ILEGAL)
     * Qué prueba: que vfwdota también exige SEW = 16 (aquí el altfmt es correcto, pero el SEW no).
     * Esperado:   excepción de instrucción ilegal y valores por defecto (con altfmt = 1 visible en el VCD).
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 14" ::: "t5");          // Marcador: t5 = 14 -> en el VCD: 0x00E00F13
    __asm__ volatile (".word 0x100072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu` con altfmt = 1
    __asm__ volatile (".word 0x922190F7");            // `vfwdota.vv v1, v2, v3`: altfmt correcto pero SEW 8 -> ILEGAL

    /* ---------------------------------------------------------------------------------
     * TEST 15: vfqwdota con SEW 16  (ILEGAL)
     * Qué prueba: que vfqwdota exige SEW = 8.
     * Esperado:   excepción de instrucción ilegal y valores por defecto.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 15" ::: "t5");          // Marcador: t5 = 15 -> en el VCD: 0x00F00F13
    __asm__ volatile (".word 0x008072D7" ::: "t0");   // `vsetvli t0, x0, e16, m1, tu, mu`
    __asm__ volatile (".word 0x9A2190F7");            // `vfqwdota.vv v1, v2, v3`: con SEW 16 -> ILEGAL

    /* ---------------------------------------------------------------------------------
     * TEST 16: configuración vectorial inválida, vill = 1  (ILEGAL)
     * Qué prueba: que con vill = 1 cualquier dot es ilegal.
     * Esperado:   en el momento de la dot: vill = 1 y vl_0 = 1; excepción de instrucción ilegal.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 16" ::: "t5");          // Marcador: t5 = 16 -> en el VCD: 0x01000F13
    __asm__ volatile (".word 0x200072D7" ::: "t0");   // `vsetvli t0, x0, ...` con el bit 29 activo (bit reservado) -> vtype inválido -> vill = 1, vl = 0
    __asm__ volatile (".word 0x9A2180F7");            // `vqwdotau.vv v1, v2, v3`: con vill = 1 -> ILEGAL
    __asm__ volatile (".word 0x000072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu`: configuración válida de nuevo (limpia vill)

    /* ---------------------------------------------------------------------------------
     * TEST 17: unidad vectorial apagada, VS = 00  (ILEGAL)
     * Qué prueba: que con mstatus.VS apagado cualquier dot es ilegal. Es la misma instrucción del test 1;
     *             la ÚNICA diferencia es VS.
     * Esperado:   excepción de instrucción ilegal y valores por defecto.
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("li t5, 17" ::: "t5");          // Marcador: t5 = 17 -> en el VCD: 0x01100F13
    __asm__ volatile (".word 0x000072D7" ::: "t0");   // `vsetvli t0, x0, e8, m1, tu, mu`
    __asm__ volatile (
        "li t0, 0x600\n"                              // t0 = 0x600 = máscara de los bits de VS
        "csrc mstatus, t0\n"                          // VS = 00 (unidad vectorial APAGADA)
        "nop\n"
        "nop\n"
        ::: "t0");
    __asm__ volatile (".word 0x9A2180F7");            // `vqwdotau.vv v1, v2, v3`: con VS apagado -> ILEGAL
    __asm__ volatile (
        "li t0, 0x600\n"                              // t0 = máscara de los bits de VS
        "csrs mstatus, t0\n"                          // VS = 11 (vuelve a estar ENCENDIDA)
        "nop\n"
        "nop\n"
        ::: "t0");

    /* ---------------------------------------------------------------------------------
     * FINAL: restauramos el handler de excepciones original del benchmark
     * --------------------------------------------------------------------------------- */
    __asm__ volatile ("csrw mtvec, %0" :: "r"(old_mtvec));   // mtvec = el valor que guardamos al principio

    return 0;
}
