import cocotb
from cocotb.triggers import RisingEdge, ClockCycles

from test import (
    S_IDLE,
    S_RUN,
    S_JUMP,
    S_SCORE,
    apply_reset,
    cooldown,
    current_level,
    expected_idle_output,
    gl_skip_lite,
    is_gatelevel,
    obs_g,
    points_in_level,
    pulse_game_reset,
    pulse_jump,
    start_clock,
    state,
    uo,
    best_level_completed,
)


async def autoplay_tick(dut):
    if state(dut) == S_RUN and obs_g(dut) == 1 and cooldown(dut) == 0:
        await pulse_jump(dut, cycles=1)


async def start_new_run(dut):
    if state(dut) == S_SCORE:
        await pulse_game_reset(dut, cycles=2)
        await ClockCycles(dut.clk, 4)
    if state(dut) == S_IDLE:
        await pulse_jump(dut, cycles=2)
        await ClockCycles(dut.clk, 2)


@cocotb.test()
async def test_full_gameplay_autoplay(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_full_gameplay_autoplay", "requires RTL-visible internals for multi-run gameplay progression")
        return

    max_attempts = 12
    reached_level_1 = False
    reached_level_3 = False
    deaths_seen = 0

    for attempt in range(max_attempts):
        await start_new_run(dut)
        died_this_attempt = False

        for i in range(5000):
            await RisingEdge(dut.clk)
            await autoplay_tick(dut)

            st = state(dut)
            lvl = current_level(dut)
            pts = points_in_level(dut)

            if lvl >= 1:
                reached_level_1 = True
            if lvl >= 3:
                reached_level_3 = True

            if i % 1000 == 0:
                dut._log.info(
                    f"[PROGRESS] attempt={attempt} cycle={i} state={st} level={lvl} "
                    f"points={pts} best={best_level_completed(dut)} cooldown={cooldown(dut)} out=0x{uo(dut):02X}"
                )

            if st == S_SCORE:
                deaths_seen += 1
                died_this_attempt = True
                dut._log.info(
                    f"[INFO] attempt={attempt} ended in SCORE with level={lvl} points={pts} "
                    f"best={best_level_completed(dut)}"
                )
                break

        if reached_level_3:
            break

        if not died_this_attempt and state(dut) != S_SCORE:
            dut._log.info(f"[INFO] attempt={attempt} ended without death; forcing restart")
            await pulse_game_reset(dut, cycles=2)
            await ClockCycles(dut.clk, 4)

    assert reached_level_1, "[FAIL] Autoplay never completed level 1 across retries"
    assert deaths_seen >= 1, "[FAIL] Autoplay never reached SCORE, so gameplay loop was not exercised"
    assert reached_level_3, "[FAIL] Autoplay never reached at least level 3 across retries"
    assert best_level_completed(dut) >= 3, (
        f"[FAIL] Best completed level should be at least 3 after retries, got {best_level_completed(dut)}"
    )

    await pulse_game_reset(dut, cycles=2)
    await ClockCycles(dut.clk, 8)
    assert state(dut) == S_IDLE, f"[FAIL] Final reset should return to IDLE, got {state(dut)}"
    assert uo(dut) == expected_idle_output(best_level_completed(dut)), (
        f"[FAIL] Idle output should show persisted best level, got 0x{uo(dut):02X}"
    )

    dut._log.info("[PASS] Full gameplay autoplay with retries test passed")