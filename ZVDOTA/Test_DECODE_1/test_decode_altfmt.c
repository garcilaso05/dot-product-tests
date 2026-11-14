#include "util.h"

int main(void) {

    // Instrucciones personalizadas
    __asm__ volatile(".word 0x100072D7");
    __asm__ volatile(".word 0x200072D7");

    __asm__ volatile("li t2, 0x100");
    __asm__ volatile(".word 0x807072D7");

    __asm__ volatile("li t2, 0x200");
    __asm__ volatile(".word 0x807072D7");

    return 0;
}

0x00000000100072D7