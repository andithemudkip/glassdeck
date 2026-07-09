"""Regenerate the embedded browser UI on every pio pre-build.

PIO's SCons wrapper does not invoke ninja on incremental builds — it runs its
own cached compile+link actions against SCons-tracked C sources. That means
CMake's CMAKE_CONFIGURE_DEPENDS never fires: editing main/index.html or
main/ui/*.{css,js} would leave the .gz.S assembly file (and the .o it compiles
to) stale, and firmware.elf would keep embedding the previous browser UI.

Fix: replicate CMake's execute_process chain here at pio pre-build time —
codegen, gzip, embed-.S — writing to the exact same paths main/CMakeLists.txt
uses. SCons's content-hash check on the .S then correctly rebuilds the .o
whenever any partial changes and skips it when nothing did.

The CMake pipeline still runs at configure time; this shim just makes it also
run on incremental builds. Byte-equivalent output means the two producers
never disagree.
"""

import gzip
import os
import subprocess
import sys

Import("env")

build_dir = env.subst("$BUILD_DIR")
project_dir = env.subst("$PROJECT_DIR")
repo_root = os.path.abspath(os.path.join(project_dir, "..", ".."))

gen_script = os.path.join(repo_root, "scripts", "gen_wifi_bridge_index.py")
template = os.path.join(project_dir, "main", "index.html")
schema = os.path.join(repo_root, "docs", "signals", "signals.yaml")

# Match the paths main/CMakeLists.txt writes to.
out_dir = os.path.join(build_dir, "esp-idf", "main")
merged_html = os.path.join(out_dir, "index.merged.html")
gz_file = os.path.join(out_dir, "index.html.gz")
deps_file = os.path.join(out_dir, "index.deps")
s_file = os.path.join(build_dir, "index.html.gz.S")


def write_if_changed(path, data):
    """Overwrite path only if data differs. Preserves mtime on no-ops so
    SCons's content-hash check stays a fast no-op when nothing changed."""
    if os.path.isfile(path):
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return True


def render_asm(gz_bytes, symbol):
    """Mirror $IDF_PATH/tools/cmake/scripts/data_file_embed_asm.cmake so the
    .S produced here is byte-identical to CMake's when the .gz is."""
    hexbytes = [f"0x{b:02x}" for b in gz_bytes]
    lines = [", ".join(hexbytes[i:i+16]) for i in range(0, len(hexbytes), 16)]
    byte_block = "\n".join(f".byte {row}" for row in lines)

    # CMake's data_file_embed_asm.cmake writes `/*` and ` * Data converted…`
    # onto the same line (`file(WRITE "…" "/*")` then `append_line(" * …")`).
    # Match that quirk so our output is byte-identical to CMake's.
    return (
        f"/* * Data converted from {gz_file}\n"
        f" */\n"
        f".data\n"
        f"#if !defined (__APPLE__) && !defined (__linux__)\n"
        f".section .rodata.embedded\n"
        f"#endif\n"
        f"\n"
        f".global {symbol}\n"
        f"{symbol}:\n"
        f"\n"
        f".global _binary_{symbol}_start\n"
        f"_binary_{symbol}_start: /* for objcopy compatibility */\n"
        f"{byte_block}\n"
        f"\n"
        f".global _binary_{symbol}_end\n"
        f"_binary_{symbol}_end: /* for objcopy compatibility */\n"
        f"\n"
        f"\n"
        f".global {symbol}_length\n"
        f"{symbol}_length:\n"
        f".long {len(gz_bytes)}\n"
        f"\n"
        f"#if defined (__linux__)\n"
        f'.section .note.GNU-stack,"",@progbits\n'
        f"#endif\n"
    )


# 1. Codegen: signals.yaml + index.html + partials → merged HTML.
# Fails loudly if a partial is missing or signals.yaml is malformed; that's
# the same M6 CI check CMake's execute_process guards.
subprocess.run(
    [
        sys.executable, gen_script,
        "--template", template,
        "--schema", schema,
        "--out", merged_html,
        "--deps-file", deps_file,
    ],
    check=True,
)

# 2. gzip -9 -n (level 9, strip mtime header for deterministic output).
# CLI gzip writes OS=3 (Unix) at header byte 9; Python's gzip module writes
# 0xff (unknown). Patch that byte so our output stays byte-identical to CMake's
# `gzip -9 -n` — otherwise the two producers would overwrite each other's .gz
# every build and force an unnecessary .o recompile on first pio run after
# configure.
with open(merged_html, "rb") as f:
    merged_bytes = f.read()
gz_bytes = bytearray(gzip.compress(merged_bytes, compresslevel=9, mtime=0))
gz_bytes[9] = 0x03
write_if_changed(gz_file, bytes(gz_bytes))

# 3. .gz → .S using the same layout as data_file_embed_asm.cmake.
asm_text = render_asm(gz_bytes, "index_html_gz")
write_if_changed(s_file, asm_text.encode())
