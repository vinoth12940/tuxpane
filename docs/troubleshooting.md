# Troubleshooting

## The Mac cannot reach Linux

On Linux, run:

```bash
tuxpane status
```

Confirm the service is `active`, the displayed addresses are reachable from the Mac, and both machines are on the same private LAN or Tailscale network. TuxPane intentionally refuses public internet addresses.

## The installer says Xorg is required

TuxPane v1 does not support Wayland. Sign out, select an Xorg/X11 session from the login screen, sign in, and rerun the installer.

## Screen capture fails

Make sure the Linux desktop user is logged in and that `DISPLAY` and `XAUTHORITY` belong to that session. Review the recent agent log with `tuxpane status`. Headless machines usually need an HDMI dummy plug.

## No encoder works

Install FFmpeg with HEVC support. Hardware encoding also requires a functioning VAAPI render device or NVIDIA NVENC driver. The installer falls back to software x265 when available.

## The machine doesn't appear when pairing

- The installer or `tuxpane pair` must be running on Linux, waiting for your Mac. It waits up to 10 minutes.
- If Linux has a firewall (`ufw`, `firewalld`), allow TuxPane: see [the firewall commands](setup.md#firewall-commands-if-you-said-no-during-install).
- macOS must be allowed to find devices on your local network: **System Settings → Privacy & Security → Local Network → TuxPane**.
- Different networks, or Tailscale only? Type the machine's Tailscale name or `100.x` address in the app.

## The certificate changed

This is expected after `tuxpane pair --reset` or a reinstall. Click **Pair Again** in the app, then run `tuxpane pair` on Linux. If you did **not** reset anything, stop and check that the address still belongs to your Linux machine.

## The codes don't match, or pairing is rejected

Click **Codes Don't Match** and start again with `tuxpane pair`. If the codes really differ every time on your home network, another device may be imitating your Linux machine; pair over Tailscale instead. "Declined on Linux" means someone answered `n` in the Linux terminal.

## ⌘Tab or ⌘Space stays on the Mac

Enable TuxPane in **System Settings → Privacy & Security → Accessibility**. Quit and reopen the app if macOS does not apply the permission immediately.

## View the service log

```bash
journalctl --user -u tuxpane -n 100 --no-pager
```

## Completely reinstall the Linux agent

```bash
tuxpane uninstall
```

Then repeat the installation and pair again. Removing the agent deletes its token and certificate, so previous Mac pairings will no longer work.
