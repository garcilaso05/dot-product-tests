#!/usr/bin/env bash

if (( $# != 1 )); then
    echo "Uso: bcompile <archivo.c>"
    exit 1
fi

if [[ ! -f "$1" || "$1" != *.c ]]; then
    echo "Error: archivo .c no encontrado."
    exit 1
fi

caller_dir="$(pwd -P)"
src="$(realpath "$1")"

root="/home/darkgarcilaso/BSC/sargantana_tile"
if [[ ! -f "$root/benchmarks.mk" ]]; then
    echo "Error: no se encuentra sargantana_tile."
    exit 1
fi

src_base="${src##*/}"      # Equivale a ${src:t} en Zsh
name="${src_base%.*}"      # Equivale a ${src:t:r} en Zsh
source_dir="$root/riscv-tests/benchmarks"
bench_dir="$source_dir/$name"          # <-- directorio por benchmark
build_dir="$root/benchmarks/benchmarks"

# Copiar el .c dentro de su propio directorio
mkdir -p "$bench_dir" "$build_dir" || exit 1
if [[ "$src" != "$bench_dir/$src_base" ]]; then
    cp -f -- "$src" "$bench_dir/$src_base" || exit 1
fi
echo "Fuente: $bench_dir/$src_base"

# Opciones originales con -O0
opts=$(sed -n 's/^BENCHMARK_GCC_OPTS = //p' "$root/benchmarks.mk" | head -n 1)
if [[ -z "$opts" ]]; then
    echo "Error: no se han encontrado las opciones de compilación."
    exit 1
fi
opts="${opts//-O2/-O0}"

printf "\nCompilando %s con -O0...\n" "$name"
rm -f "$build_dir/$name.riscv"

# Llamar directamente al Makefile interno de riscv-tests/benchmarks
make -C "$build_dir" \
    -f "$source_dir/Makefile" \
    src_dir="$source_dir" \
    XLEN=64 \
    RISCV_GCC_OPTS="$opts" \
    bmarks="$name" \
    "$name.riscv" || exit 1

binary="$build_dir/$name.riscv"
if [[ ! -f "$binary" ]]; then
    echo "Error: no se ha generado $binary"
    exit 1
fi

output="$caller_dir/$name.riscv"
cp -f -- "$binary" "$output" || exit 1
printf "\nBenchmark compilado: %s\n" "$output"

# Simular desde la raíz del proyecto (subshell)
(
    cd "$root" || exit 1

    printf "\nSimulando (VCD)...\n"
    ./sim +load="$binary" +vcd || exit 1

    printf "\nSimulando (Konata)...\n"
    ./sim +load="$binary" +konata_dump || exit 1

    mv -f dump.vcd    "$caller_dir/$name.vcd"        || exit 1
    mv -f konata.txt  "$caller_dir/$name.konata.txt" || exit 1
) || { echo "Error en la simulación."; exit 1; }

printf "\nListo, en %s:\n" "$caller_dir"
echo "  $name.riscv"
echo "  $name.vcd         -> gtkwave $name.vcd"
echo "  $name.konata.txt  -> konata $name.konata.txt"