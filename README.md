# Game Lab

Work on games with Hermes: mod a game on a safe copy, translate its text without breaking it, and playtest it by pressing and holding keys and reporting honestly.

**Why one plugin:** mod it, translate it, then playtest it. Those are three steps of the same job, so they live together.

**Who it is for:** someone who owns a PC game and wants Hermes to help change it, translate it and check that it still plays, without risking the original install.

## The three parts

| Part | What it is for | Tools |
|---|---|---|
| ModLab | Copy a game folder into a lab, apply mod ZIPs as revisions you can inspect and roll back, and drive Universal Modder and Reverse Engineer Anything for recon, assets, builds and tests. The original folder is only read. | `modlab_resources`, `modlab_toolkit`, `modlab_rea_native`, `modlab_create`, `modlab_inspect`, `modlab_apply`, `modlab_rollback`, `modlab_select_preserved` |
| Game Localization Studio | Make translation drafts for RPG Maker MV/MZ message text. Every line is addressed to its source, control codes and row widths are checked, and the result is exported as a new file. | `localize_inspect`, `localize_get`, `localize_translate`, `localize_validate`, `localize_export`, `localize_list_drafts` |
| Playtest Pilot | Play-test an app in a window you select, one action at a time (click, key, or hold up to three keys for up to 3 seconds), with a capture of the window after every action and a separate honest record of what passed, failed or is uncertain. | `playtest_start`, `playtest_action`, `playtest_replay`, `playtest_observe`, `playtest_report` |

19 tools, one hook (`pre_tool_call`, which asks for your approval before any held key), three skills (`modlab`, `game-localization-studio`, `playtest-pilot`) and one Desktop page for the translation drafts.

These are the same three plugins that are also published on their own (ModLab 0.2.0, Game Localization Studio 0.2.1, Playtest Pilot 0.3.0), bundled with their behaviour unchanged. Tool names, the approval rule and the safety checks are the ones from those plugins.

**At a glance**

- **Install:** `hermes plugins install flabanabba8/game-lab`, then `hermes plugins enable game-lab`.
- **Needs:** Hermes 0.22 or later and a game you own or may translate.
  - ModLab also needs the companion tools Universal Modder (`um`) and Reverse Engineer Anything (`rea`), installed by you, for the steps that use them. Its optional setting `rea_native_tool` names a native REA tool already registered in your Hermes.
  - Game Localization Studio needs RPG Maker MV/MZ JSON data files. Hermes itself does the translating; no key or model is required by the plugin.
  - Playtest Pilot needs Hermes `computer_use` available and authorized and a Linux X11 (or XWayland) display. Holding keys also needs `xdotool`. The scene-shift hint uses `ffmpeg` and `numpy` when they are installed; without them the hint is left out.
- **Platform:** Linux is the only platform checked.
- **Internet:** the plugin makes no network calls of its own: no telemetry, update checks or model calls. Any network use comes from the companion tools you choose to run with ModLab.
- **Keys and accounts:** none read or stored.
- **Approvals:** every held key asks through this plugin's own approval box; every other playtest action goes through your Hermes `computer_use` approval policy.

## Where things are stored

Each part keeps its data in its own Hermes plugin-data folder, so nothing is shared between them: `game-lab-modlab` (labs, revisions, toolkit logs), `game-lab-localization` (copies of the source file, drafts and exports) and `game-lab-playtest` (playtest receipts). These are separate from the folders of the stand-alone plugins, so data written by those is not picked up; export or copy it over by hand if you need it. Data stays until you remove it.

## Limits

- The parts do not talk to each other. You (or the agent) carry a game from one step to the next.
- ModLab works on a copy and copies whole revisions, so it needs disk space and time. It does not guarantee a copied game launches (launchers, DRM and saves outside the folder can get in the way), it does not install anything into your real game, and it blocks the publish and pull-request routes of the companion tools. No real mod and no game launch has been tested by us.
- Game Localization Studio handles RPG Maker MV/MZ message text, choices and selected database fields, not scripts, images or pixel layout. A structural pass is not proof of in-game rendering, and the message row limit comes from you. Another engine needs its own importer.
- Playtest Pilot records what you or the agent observe; the observation is not proof. Screenshots are not stored. Only the one live run described in VERIFICATION.md has been done against a real game; other games and replay are untested. Windows is unsupported.
- Hermes Desktop gets one page, "Game Lab", with the editable translation draft view of Game Localization Studio (and its dashboard route). ModLab and Playtest Pilot have no page. The page was tested only in a headless browser fixture with a stub of the Hermes Desktop SDK, not in the real Desktop app.
- The plugin bundles no game files, game data, media, SDKs or binaries.

## Credits and licences

- Universal Modder and Reverse Engineer Anything are separate projects used by ModLab through their command-line tools. Their authors and licences apply; nothing from them is bundled.
- RPG Maker MV is a product of its owners. The official MV event interpreter and the TextManager source from the public `rpgtkoolmv/corescript` repository were used in test fixtures only; they are not bundled, and Game Localization Studio is not affiliated with or endorsed by RPG Maker.
- Playtest Pilot calls the host `computer_use` tool and uses `xdotool`, `ffmpeg` and `numpy` if you have them installed; none of them is bundled.
- Licence: GPL-3.0-or-later (see LICENSE).

## AI assistance

Written with AI coding assistants (Anthropic Claude and OpenAI Codex agents) under the maintainer's direction. What was actually tested is listed in VERIFICATION.md.

## Reading further

[Bundled wiki](llmwiki/index.md), [tool contracts](llmwiki/tools.md), [verification record](VERIFICATION.md).
