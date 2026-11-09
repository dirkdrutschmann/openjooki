# GIO TLS backend for the Jooki

`../system/libgiognutls.so` is the GnuTLS TLS backend for GIO, from
[GNOME glib-networking 2.62.4](https://gitlab.gnome.org/GNOME/glib-networking/-/tree/6708b357c59d7655f10d7b69c194178c9ccc447f).
The source is unmodified and is licensed LGPL-2.1-or-later; its license is in the upstream
[`COPYING`](https://gitlab.gnome.org/GNOME/glib-networking/-/blob/6708b357c59d7655f10d7b69c194178c9ccc447f/COPYING).

The module was built for the Jooki 2 firmware ABI: ELF32 little-endian MIPS32r2, O32, musl,
GLib/GIO 2.62.0, and GnuTLS 3.6.12. It uses only the GnuTLS backend; OpenSSL and proxy backends are
disabled. The firmware already supplies the libraries and the system CA bundle at
`/etc/ssl/certs/ca-certificates.crt`. Certificate and hostname validation remain enabled.

The A/B updater installs the module at `/usr/lib/gio/modules/libgiognutls.so`, runs the firmware's
`/usr/libexec/gio-querymodules` against that directory on the spare partition, and checks that the
generated cache registers `gnutls` before it switches partitions.

Build provenance:

- Upstream source commit: `6708b357c59d7655f10d7b69c194178c9ccc447f` (tag `2.62.4`).
- Cross compiler: `mipsel-linux-gnu-gcc` 9.4.0; Meson 0.53.2.
- Linked against the libraries extracted from Jooki firmware `2.4.21-offline.6`.
- `-nostdlib` was used with the firmware's Musl `libc.so` and the compiler's static `libgcc.a`;
  this avoids adding the build host's GLIBC to the device module.
- Binary SHA-256: `5d222334a58058808aff3981811dc34d77592063bfb29d281d60df49cc5cec64`.

Meson backend options were `-Dgnutls=enabled -Dopenssl=disabled -Dlibproxy=disabled
-Dgnome_proxy=disabled -Dinstalled_tests=false`. The build used a cross file targeting MIPS32r2
little-endian O32 and a sysroot containing the firmware's GLib/GIO and GnuTLS development headers
and libraries.
