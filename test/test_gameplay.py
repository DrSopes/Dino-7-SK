import cocotb
from cocotb.triggers import RisingEdge, ClockCycles, Timer

from test import (
    S_IDLE,
    S_RUN,
    S_JUMP,
    S_HIT,
    S_SCORE,
    S_WIN,
    WIN_ON,
    apply_reset,
    best_level_completed,
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
)


def dut_i(dut):
    return dut.user_project


async def settle():
    await Timer(1, unit="ns")


async def wait_cycles_or_until(dut, predicate, timeout_cycles, label):
    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if predicate():
            dut._log.info(f"[PASS] {label} after {i+1} cycles")
            return
    raise AssertionError(f"[FAIL] Timeout waiting for {label}")


async def autoplay_tick(dut):
    if state(dut) == S_RUN and obs_g(dut) == 1 and cooldown(dut) == 0:
        await pulse_jump(dut, cycles=1)


async def start_run_from_idle(dut):
    if state(dut) != S_IDLE:
        raise AssertionError(f"[FAIL] Expected IDLE before start, got state={state(dut)}")
    await pulse_jump(dut, cycles=2)
    await wait_cycles_or_until(dut, lambda: state(dut) != S_IDLE, 20, "leave IDLE")


async def return_to_idle_from_score(dut):
    if state(dut) != S_SCORE:
        raise AssertionError(f"[FAIL] Expected SCORE before reset, got state={state(dut)}")
    best_before = best_level_completed(dut)
    await pulse_game_reset(dut, cycles=2)
    await ClockCycles(dut.clk, 8)
    assert state(dut) == S_IDLE, f"[FAIL] Reset from SCORE should return to IDLE, got {state(dut)}"
    assert uo(dut) == expected_idle_output(best_before), (
        f"[FAIL] IDLE display should preserve best level, got 0x{uo(dut):02X}"
    )


@cocotb.test()
async def test_gameplay_state_walkthrough(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_gameplay_state_walkthrough", "requires RTL-visible internals")
        return

    assert state(dut) == S_IDLE, f"[FAIL] Expected IDLE after reset, got {state(dut)}"
    await start_run_from_idle(dut)

    seen_run = False
    seen_jump = False
    for _ in range(1200):
        await RisingEdge(dut.clk)
        seen_run |= (state(dut) == S_RUN)
        seen_jump |= (state(dut) == S_JUMP)
        if state(dut) == S_HIT:
            break

    assert seen_run, "[FAIL] Gameplay never visited S_RUN"
    assert seen_jump, "[FAIL] Gameplay never visited S_JUMP"
    assert state(dut) == S_HIT, f"[FAIL] Gameplay should eventually hit and enter S_HIT, got {state(dut)}"
    assert uo(dut) == 0xFF, f"[FAIL] HIT output should be 0xFF, got 0x{uo(dut):02X}"

    await wait_cycles_or_until(dut, lambda: state(dut) == S_SCORE, 200, "enter SCORE")
    await return_to_idle_from_score(dut)
    dut._log.info("[PASS] Gameplay state walkthrough test passed")


@cocotb.test()
async def test_gameplay_progress_and_persistence(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_gameplay_progress_and_persistence", "requires RTL-visible internals")
        return

    max_attempts = 12
    deaths_seen = 0
    reached_level_1 = False
    score_grew = False
    best_seen = 0

    for attempt in range(max_attempts):
        if state(dut) == S_SCORE:
            await pulse_game_reset(dut, cycles=2)
            await ClockCycles(dut.clk, 6)
        if state(dut) == S_IDLE:
            await pulse_jump(dut, cycles=2)
            await ClockCycles(dut.clk, 2)

        local_max_points = points_in_level(dut)

        for i in range(3000):
            await RisingEdge(dut.clk)
            await autoplay_tick(dut)

            local_max_points = max(local_max_points, points_in_level(dut))
            best_seen = max(best_seen, best_level_completed(dut))
            if points_in_level(dut) >= 1:
                score_grew = True
            if current_level(dut) >= 1:
                reached_level_1 = True

            if i % 1000 == 0:
                dut._log.info(
                    f"[PROGRESS] attempt={attempt} cycle={i} state={state(dut)} level={current_level(dut)} "
                    f"points={points_in_level(dut)} best={best_level_completed(dut)} out=0x{uo(dut):02X}"
                )

            if state(dut) == S_SCORE:
                deaths_seen += 1
                dut._log.info(
                    f"[INFO] attempt={attempt} ended in SCORE with level={current_level(dut)} "
                    f"points={points_in_level(dut)} best={best_level_completed(dut)} local_max_points={local_max_points}"
                )
                break

        if reached_level_1 and deaths_seen >= 1:
            break

    assert score_grew, "[FAIL] Autoplay never increased points_in_level"
    assert deaths_seen >= 1, "[FAIL] Gameplay never exercised death -> SCORE path"
    assert reached_level_1, "[FAIL] Autoplay never completed level 1"
    assert best_seen >= 1, f"[FAIL] best_level_completed should reach at least 1, got {best_seen}"

    await return_to_idle_from_score(dut)
    assert best_level_completed(dut) >= 1, (
        f"[FAIL] Best level should persist after reset, got {best_level_completed(dut)}"
    )
    dut._log.info("[PASS] Gameplay progress and persistence test passed")


@cocotb.test()
async def test_gameplay_victory_path_assisted(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_gameplay_victory_path_assisted", "requires RTL-visible internals")
        return

    dut_i(dut).state.value = S_JUMP
    dut_i(dut).points_in_level.value = 6
    dut_i(dut).best_level_completed.value = 6
    dut_i(dut).current_level.value = 6
    dut_i(dut).frame_period.value = 0
    dut_i(dut).difficulty_step.value = 1
    dut_i(dut).clk_div.value = 0
    dut_i(dut).obs_passed.value = 1
    dut_i(dut).obs_c.value = 0
    dut_i(dut).obs_g.value = 0
    dut_i(dut).obs_f.value = 0
    dut_i(dut).jump_timer.value = 7
    await settle()

    await RisingEdge(dut.clk)
    await settle()
    assert state(dut) == S_WIN, f"[FAIL] Assisted final clear should enter S_WIN, got {state(dut)}"
    assert uo(dut) == WIN_ON, f"[FAIL] WIN should light all seven segments, got 0x{uo(dut):02X}"

    flashes = 1
    prev_on = False
    for _ in range(300):
        await RisingEdge(dut.clk)
        await settle()
        now_on = (uo(dut) == WIN_ON)
        if now_on and not prev_on:
            flashes += 1
        prev_on = now_on
        if state(dut) == S_IDLE:
            break

    assert flashes == 7, f"[FAIL] WIN should flash 7 times, observed {flashes}"
    assert state(dut) == S_IDLE, f"[FAIL] WIN should finish in IDLE, got {state(dut)}"
    assert best_level_completed(dut) == 7, (
        f"[FAIL] Winning should set best_level_completed to 7, got {best_level_completed(dut)}"
    )
    assert uo(dut) == expected_idle_output(7), (
        f"[FAIL] IDLE after WIN should show 7, got 0x{uo(dut):02X}"
    )
    dut._log.info("[PASS] Gameplay victory path assisted test passed")