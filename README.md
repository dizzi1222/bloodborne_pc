# Hunter's Atlas 0.1.2 for bbport 1.9.8.4

Fullscreen map for Bloodborne 1.09 on Windows. This build requires the bbport 1.9.8.4 native module host with the `1.9.8.4-atlas.2` marker. The complete mod ZIP contains the DLL, maps, art, configuration and source.

## Installation

1. Close Bloodborne and the launcher.
2. Extract the complete ZIP into `bbport-windows\mods\Hunter's Atlas`. If updating an existing 0.1.2 install, overwrite the files in that same folder, including `config\settings.ini`. The manifest should be at `mods\Hunter's Atlas\bbport-native-mod.json`.
3. Start bbport and enable **Hunter's Atlas** in **Mods & patches**.

## Controls

| Action | Keyboard / mouse | Controller |
| --- | --- | --- |
| Open or close map | M | L3 (click left stick) |
| Open from the quick menu | Click Map | Select Map and confirm |
| Move pointer | Mouse | Left stick |
| Pan | Drag | Right stick |
| Zoom | Wheel or + / - | L2 / R2 |
| Previous / next lamp | Q / E | L1 / R1 |
| Confirm / back | Click or Enter / Escape | Cross or A / Circle or B |
| Recenter / elevation shading | Home / H | Triangle or Y / Square or X |
| Passage view on illustrated maps | V | R3 (click right stick) |
| Atlas settings | F1 while the map is open | |

The package selects L3 by default. On illustrated maps, R3 and V cycle Auto, Upper, Lower and back to Auto.

## Source

The native module source is in `source/`. Build in MSYS2 CLANG64 with CMake, Ninja, Clang, Vulkan, SDL3, nlohmann-json, OpenSSL and zlib.

```sh
cmake -S source/bbport-native-mod -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
cmake --build build --target hunters_atlas
llvm-strip --strip-debug -o hunters_atlas.dll build/hunters_atlas.dll
```

The launcher checks the DLL and map index SHA-256 recorded in `bbport-native-mod.json`. A locally rebuilt DLL requires its own hash in that manifest.

Hunter's Atlas 3.1 by [MikeTat1988 and contributors](https://github.com/MikeTat1988/HuntersAtlas). bbport by [Supermedo and contributors](https://github.com/Supermedo/bloodborne_pc). Native module adaptation by dizziRD. See `LICENSE` and the ImGui license included in the source tree.
