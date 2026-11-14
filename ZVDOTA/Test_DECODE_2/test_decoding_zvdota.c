#include "util.h"

#define MARK(n)  __asm__ volatile ("li t5, " #n ::: "t5")   /* marker: addi t5,x0,n -> inst = 0x00n00F13 */
#define STR_(x)  #x
#define STR(x)   STR_(x)                                     /* expands the macro first, then stringifies */
#define W(w)     __asm__ volatile (".word " STR(w))          /* raw instruction word */
#define FS_OFF() __asm__ volatile ("li t0, 0x6000\ncsrc mstatus, t0\nnop\nnop" ::: "t0")
#define FS_ON()  __asm__ volatile ("li t0, 0x6000\ncsrs mstatus, t0\nnop\nnop" ::: "t0")
#define VS_OFF() __asm__ volatile ("li t0, 0x600\ncsrc mstatus, t0\nnop\nnop"  ::: "t0")
#define VS_ON()  __asm__ volatile ("li t0, 0x600\ncsrs mstatus, t0\nnop\nnop"  ::: "t0")

#define VSET_E8_A0   0x000072D7   /* vsetvli t0,x0,e8,m1,tu,mu           */
#define VSET_E8_A1   0x100072D7   /* same, altfmt=1                      */
#define VSET_E16_A0  0x008072D7   /* e16, altfmt=0                       */
#define VSET_E16_A1  0x108072D7   /* e16, altfmt=1                       */
#define VSET_E32_A0  0x010072D7   /* e32, altfmt=0                       */
#define VSET_VILL    0x200072D7   /* reserved bit 9 set -> vill          */
#define VSET_VL0     0x000372D7   /* vsetvli t0,t1,e8 (t1 = 0 -> vl = 0) */

#define VQWDOTAU     0x9A2180F7   /* vqwdotau.vv v1,v2,v3                */
#define VQWDOTAU_M   0x982180F7   /* same, masked (vm=0)                 */
#define VQWDOTAS     0x9E2180F7
#define VFWDOTA      0x922190F7
#define VFQWDOTA     0x9A2190F7
#define VFQWDOTA_ALT 0x9E2190F7
#define VQWDOTAU_VD_EQ_VS1 0x9A2181F7   /* vd = v3 = vs1 */
#define VQWDOTAU_VD_EQ_VS2 0x9A218177   /* vd = v2 = vs2 */
#define BAD_ENCODING 0x922180F7         /* funct6=0x24 with funct3=0: not in the table */

/* Trap handler that skips the faulting instruction, so illegal cases do not end the program */
__asm__ (".text\n .align 2\n .globl skip_trap\n"
         "skip_trap:\n csrr t6, mepc\n addi t6, t6, 4\n csrw mepc, t6\n mret\n");
extern void skip_trap(void);

void test(void) {
    MARK(1);  W(VSET_E8_A0);  W(VQWDOTAU);
    MARK(2);  W(VSET_E8_A1);  W(VQWDOTAS);
    MARK(3);  W(VSET_E16_A1); W(VFWDOTA);
    MARK(4);  W(VSET_E8_A0);  W(VFQWDOTA);
    MARK(5);  W(VSET_E8_A1);  W(VFQWDOTA_ALT);
    MARK(6);  W(VSET_E16_A0); W(VQWDOTAU);
    MARK(7);  W(VSET_E8_A0);  W(VQWDOTAU_M);
    MARK(8);  __asm__ volatile ("li t1, 0" ::: "t1"); W(VSET_VL0); W(VQWDOTAU);
    MARK(9);  W(VSET_E8_A0);  FS_OFF(); W(VQWDOTAU); FS_ON();
    MARK(10); W(VSET_E8_A0);  W(VQWDOTAU_VD_EQ_VS1);
    MARK(11); W(VSET_E8_A0);  W(VQWDOTAU_VD_EQ_VS2);
    MARK(12); W(VSET_E8_A0);  W(BAD_ENCODING);
    MARK(13); W(VSET_E32_A0); W(VQWDOTAU);
    MARK(14); W(VSET_E16_A0); W(VFWDOTA);
    MARK(15); W(VSET_E8_A1);  W(VFWDOTA);
    MARK(16); W(VSET_E16_A0); W(VFQWDOTA);
    MARK(17); W(VSET_E8_A0);  FS_OFF(); W(VFQWDOTA); FS_ON();
    MARK(18); W(VSET_VILL);   W(VQWDOTAU);   W(VSET_E8_A0);
    MARK(19); W(VSET_E8_A0);  VS_OFF(); W(VQWDOTAU); VS_ON();
}



int main(void) {

    unsigned long old_mtvec;
    __asm__ volatile ("csrr %0, mtvec" : "=r"(old_mtvec));
    __asm__ volatile ("csrw mtvec, %0" :: "r"(skip_trap));
    __asm__ volatile ("li t0, 0x6600\ncsrs mstatus, t0" ::: "t0");   // VS and FS on
    test();
    __asm__ volatile ("csrw mtvec, %0" :: "r"(old_mtvec));

    return 0;
}