# Dino-7 Tiny Tapeout game

This project implements a one-button dinosaur-style reflex game for Tiny Tapeout. The player starts from `IDLE`, jumps over procedurally generated obstacles, advances through seven difficulty levels, and wins after clearing level 7. The game is designed to run both on hardware and in cocotb simulation, with fast timing selected when `COCOTB_SIM` is defined.

## Controls

The design uses the Tiny Tapeout standard I/O layout:

- `ui_in[0]`: jump button.
- `ui_in[1]`: in-game reset.
- `ui_in[3:2]`: starting difficulty preset.
- `ui_in[7:4]`: 4-bit seed for the obstacle generator.
- `uo_out[7:0]`: game display and debug output.
- `uio_in`, `uio_out`, `uio_oe`: unused in gameplay.

A jump from `IDLE` starts the game. During gameplay, the player can only jump from `S_RUN` when the cooldown counter is zero.

## Game flow

The game uses these states:

- `S_IDLE`: waiting to start, 7-segment display shows the best completed level with decimal point on.
- `S_RUN`: player is on the ground.
- `S_JUMP`: player is airborne for a short timer-controlled duration.
- `S_HIT`: collision feedback, all segments on.
- `S_SCORE`: post-death score/best-level display blink phase.
- `S_WIN`: final celebration after clearing level 7.

Obstacles move through a three-stage pipeline: `obs_c -> obs_g -> obs_f -> obs_passed`. A collision happens when `obs_f == 1` while the state is `S_RUN`. A successful jump scores when `obs_passed == 1` while the state is `S_JUMP`.

## Scoring and levels

`points_in_level` counts the successful jumps within the current level. When the player reaches 7 points in a level, the game either advances to the next level or enters `S_WIN` if level 7 has been completed.

`current_level` tracks the active level from 0 to 6, and `best_level_completed` stores the highest cleared level from 0 to 7. On every completed level, `frame_period` is reduced by `difficulty_step`, which makes the game faster.

## Outputs during gameplay

During `S_RUN` and `S_JUMP`, `uo_out` is used as a compact debug/gameplay view:

- `uo_out[0] = obs_c`
- `uo_out[1] = obs_g`
- `uo_out[2] = (state == S_RUN)`
- `uo_out[3] = obs_passed`
- `uo_out[4] = (state == S_JUMP)`
- `uo_out[5] = unused_ok`
- `uo_out[6] = obs_f`
- `uo_out[7] = (cooldown_timer > 0)`

Outside gameplay:

- In `S_IDLE`, the display shows `best_level_completed` on the 7-segment display with decimal point on.
- In `S_HIT`, all outputs are set to `8'hFF`.
- In `S_SCORE`, the display alternates between current points and best completed level.
- In `S_WIN`, the 7-segment display flashes all seven segments seven times, then returns to `S_IDLE`.

## Simulation and tests

The project is intended to be simulated with cocotb and Icarus Verilog.

Run the full RTL regression:

```sh
make -B
```

Run a single gameplay-only test:

```sh
cd test
COCOTB_TEST_MODULES=test_gameplay COCOTB_TESTCASE=test_full_gameplay_autoplay make -f Makefile results.xml
```

Run the complete gameplay-oriented suite:

```sh
cd test
COCOTB_TEST_MODULES=test,test_extra,test_gameplay make -f Makefile results.xml
```

## Waveforms

To inspect the simulation:

```sh
gtkwave tb.fst
```

Useful internal signals to observe are:

- `state`
- `points_in_level`
- `current_level`
- `best_level_completed`
- `frame_period`
- `frame_tick`
- `obs_c`, `obs_g`, `obs_f`, `obs_passed`
- `jump_timer`
- `cooldown_timer`
- `uo_out`

For clean debugging, prefer generating a waveform from a single test instead of the whole regression, because the full regression concatenates many scenarios into one `tb.fst`.
