# NOTICE

This repository (spektralab-fnos) contains **build and packaging scripts
only**. The binaries it produces are built from the upstream project at the
commit pinned in `UPSTREAM_PIN`:

- Upstream: https://github.com/JamesQiu2005/SpektraLab
- Engine derived from spektrafilm by Andrea Volpato (GPL-3.0-or-later):
  https://github.com/andreavolpato/spektrafilm

Licenses carried by the produced image and host bundle:

| Component | License |
|---|---|
| SpektraLab host & engine | GPL-3.0-or-later (this repo's LICENSE; corresponding source = the pinned upstream checkout) |
| spektrafilm film/paper profiles & enlarger LUTs | CC BY-SA 4.0 |
| LibRaw 0.22.2 | LGPL-2.1 (of LGPL/CDDL) |
| Vulkan-Headers | Apache-2.0 OR MIT |
| stb_image / stb_image_write / stb_truetype | public domain / MIT |
| volk | MIT |
| Mesa lavapipe (in the runtime image, from Debian) | LGPL-2.1+ (Mesa) |

The film and paper stock names are trademarks of their owners, used only to
identify which public datasheets the profiles are based on. SpektraLab is not
affiliated with or endorsed by them, nor by Capture One A/S.

These scripts are themselves GPL-3.0-or-later.
