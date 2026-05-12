import cocotb
from cocotb.triggers import RisingEdge

from test import (
    S_IDLE,
    S_RUN,
    S_JUMP,
    S_WIN,
    WIN_ON,
    apply_reset,
    best_level_completed,
    cooldown,
    current_level,
    expected_idle_output,
    gl_skip_lite,
    has_bit,
    is_gatelevel,
    obs_g,
    points_in_level,
    pulse_jump,
    start_clock,
    state,
    uo,
)


async def autoplay_step(dut):
    if state(dut) == S_RUN and obs_g(dut) == 1 and cooldown(dut) == 0:
        await pulse_jump(dut, cycles=1)


@cocotb.test()
async def test_full_gameplay_autoplay(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_full_gameplay_autoplay", "requires RTL-visible internals for gameplay progression")
        return

    dut._log.info("[STEP] Starting autoplay session")
    await pulse_jump(dut, cycles=2)

    reached_level_1 = False
    reached_level_3 = False
    reached_win = False
    flashes = 0
    prev_win_on = False

    for i in range(30000):
        await RisingEdge(dut.clk)
        await autoplay_step(dut)

        st = state(dut)
        lvl = current_level(dut)
        pts = points_in_level(dut)
        out = uo(dut)

        if lvl >= 1:
            reached_level_1 = True
        if lvl >= 3:
            reached_level_3 = True

        win_on = (out == WIN_ON)
        if win_on and not prev_win_on:
            flashes += 1
        prev_win_on = win_on

        if st == S_WIN:
            reached_win = True

        if i % 2000 == 0:
            dut._log.info(
                f"[PROGRESS] cycle={i} state={st} level={lvl} points={pts} "
                f"best={best_level_completed(dut)} cooldown={cooldown(dut)} out=0x{out:02X}"
            )

        if reached_win and st == S_IDLE:
            break

    assert reached_level_1, "[FAIL] Autoplay never completed level 1"
    assert reached_level_3, "[FAIL] Autoplay never reached at least level 3"
    assert reached_win, "[FAIL] Autoplay never entered S_WIN"
    assert flashes >= 7, f"[FAIL] Expected at least 7 WIN flashes, observed {flashes}"
    assert state(dut) == S_IDLE, f"[FAIL] Game should return to IDLE after WIN, got {state(dut)}"
    assert best_level_completed(dut) == 7, f"[FAIL] Best completed level should be 7, got {best_level_completed(dut)}"
    assert current_level(dut) == 0, f"[FAIL] Current level should reset to 0 after WIN, got {current_level(dut)}"
    assert points_in_level(dut) == 0, f"[FAIL] Points should reset to 0 after WIN, got {points_in_level(dut)}"
    assert uo(dut) == expected_idle_output(7), (
        f"[FAIL] IDLE display after WIN should show best level 7, got 0x{uo(dut):02X}"
    )
    assert has_bit(uo(dut), 1 << 7), "[FAIL] DP should be on in IDLE after WIN"

    dut._log.info("[PASS] Full gameplay autoplay test passed")
