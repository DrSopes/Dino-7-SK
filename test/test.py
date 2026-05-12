import os
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

SEG_A = 1 << 0
SEG_B = 1 << 1
SEG_C = 1 << 2
SEG_D = 1 << 3
SEG_E = 1 << 4
SEG_F = 1 << 5
SEG_G = 1 << 6
SEG_DP = 1 << 7

ALL_ON = 0xFF
WIN_ON = 0x7F

S_IDLE = 0
S_RUN = 1
S_JUMP = 2
S_HIT = 3
S_SCORE = 4
S_WIN = 5

GL_EXTENDED = os.getenv("GL_EXTENDED", "0") == "1"
GL_TIMEOUT_SCALE = int(os.getenv("GL_TIMEOUT_SCALE", "20"))


def sig_u(obj, name="signal"):
    v = obj.value
    try:
        return v.to_unsigned() if hasattr(v, "to_unsigned") else int(v)
    except ValueError:
        raise AssertionError(f"[FAIL] {name} contains X/Z: {v!s}")


def dut_i(dut):
    return dut.user_project


def has_internal(dut, name):
    return getattr(dut_i(dut), name, None) is not None


def internal_u(dut, name):
    obj = getattr(dut_i(dut), name, None)
    if obj is None:
        return None
    return sig_u(obj, name)


def is_gatelevel(dut):
    return not has_internal(dut, "state")


def is_gl_extended():
    return GL_EXTENDED


def scaled_timeout(dut, base_cycles):
    if is_gatelevel(dut):
        return base_cycles * GL_TIMEOUT_SCALE
    return base_cycles


def uo(dut):
    return sig_u(dut.uo_out, "uo_out")


def ui(dut):
    return sig_u(dut.ui_in, "ui_in")


def state(dut):
    return internal_u(dut, "state")


def points_in_level(dut):
    return internal_u(dut, "points_in_level")


def best_level_completed(dut):
    return internal_u(dut, "best_level_completed")


def current_level(dut):
    return internal_u(dut, "current_level")


def cooldown(dut):
    return internal_u(dut, "cooldown_timer")


def frame_period(dut):
    return internal_u(dut, "frame_period")


def difficulty_step(dut):
    return internal_u(dut, "difficulty_step")


def obs_c(dut):
    return internal_u(dut, "obs_c")


def obs_g(dut):
    return internal_u(dut, "obs_g")


def obs_f(dut):
    return internal_u(dut, "obs_f")


def obs_passed(dut):
    return internal_u(dut, "obs_passed")


def has_bit(value, bitmask):
    return (value & bitmask) != 0


def seg7_encode(val):
    table = {
        0: 0x3F,
        1: 0x06,
        2: 0x5B,
        3: 0x4F,
        4: 0x66,
        5: 0x6D,
        6: 0x7D,
        7: 0x07,
        8: 0x7F,
        9: 0x6F,
    }
    return table.get(int(val) & 0xF, 0x00)


def expected_idle_output(best_level):
    return 0x80 | seg7_encode(best_level)


def gl_skip_lite(dut, name, reason):
    dut._log.info(f"[SKIP-LITE] {name}: {reason}")


def log_state(dut, tag="STATE"):
    if is_gatelevel(dut):
        dut._log.info(f"[{tag}] uo_out=0x{uo(dut):02X} (gate-level: internal nets unavailable)")
        return

    dut._log.info(
        f"[{tag}] "
        f"uo_out=0x{uo(dut):02X} "
        f"state={state(dut)} "
        f"points_in_level={points_in_level(dut)} "
        f"best_level_completed={best_level_completed(dut)} "
        f"current_level={current_level(dut)} "
        f"cooldown={cooldown(dut)} "
        f"frame_period={frame_period(dut)} "
        f"obs(c/g/f/p)=({obs_c(dut)}/{obs_g(dut)}/{obs_f(dut)}/{obs_passed(dut)})"
    )


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    await ClockCycles(dut.clk, 1)


async def apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111):
    dut.ena.value = 1
    dut.uio_in.value = 0
    dut.ui_in.value = ((seed_bits & 0xF) << 4) | ((difficulty_bits & 0x3) << 2)
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)
    log_state(dut, "AFTER_RESET")


async def settle():
    await Timer(1, unit="ns")


async def step_clk(dut, cycles=1):
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        await settle()


async def pulse_jump(dut, cycles=2):
    dut.ui_in.value = ui(dut) | 0x01
    await ClockCycles(dut.clk, cycles)
    dut.ui_in.value = ui(dut) & ~0x01


async def pulse_game_reset(dut, cycles=2):
    dut.ui_in.value = ui(dut) | 0x02
    await ClockCycles(dut.clk, cycles)
    dut.ui_in.value = ui(dut) & ~0x02


async def hold_jump_until_output_leaves_idle(dut, timeout_cycles=80):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    dut._log.info("[STEP] Holding jump until output leaves idle")
    start = uo(dut)
    dut.ui_in.value = ui(dut) | 0x01

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if uo(dut) != start:
            dut._log.info(f"[PASS] Left idle output after {i+1} cycles")
            dut.ui_in.value = ui(dut) & ~0x01
            await ClockCycles(dut.clk, 1)
            log_state(dut, "AFTER_START")
            return

    dut.ui_in.value = ui(dut) & ~0x01
    raise AssertionError("[FAIL] Output never left IDLE while jump was held")


async def hold_jump_until_start(dut, timeout_cycles=80):
    if is_gatelevel(dut):
        await hold_jump_until_output_leaves_idle(dut, timeout_cycles)
        return

    dut._log.info("[STEP] Holding jump until game leaves IDLE")
    dut.ui_in.value = ui(dut) | 0x01

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if state(dut) != S_IDLE:
            dut._log.info(f"[PASS] Left IDLE after {i+1} cycles")
            dut.ui_in.value = ui(dut) & ~0x01
            await ClockCycles(dut.clk, 1)
            log_state(dut, "AFTER_START")
            return

    dut.ui_in.value = ui(dut) & ~0x01
    raise AssertionError("[FAIL] Game never left IDLE")


async def wait_for_output_change(dut, timeout_cycles=120, label="output change"):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    start = uo(dut)
    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        now = uo(dut)
        if now != start:
            dut._log.info(f"[PASS] {label} after {i+1} cycles: 0x{start:02X} -> 0x{now:02X}")
            return now
    raise AssertionError(f"[FAIL] No {label} within {timeout_cycles} cycles")


async def wait_for_state(dut, target_state, timeout_cycles=400, label="state"):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    if is_gatelevel(dut):
        raise AssertionError(f"[FAIL] wait_for_state({label}) requires RTL-visible internal nets")

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if state(dut) == target_state:
            dut._log.info(f"[PASS] Reached {label} after {i+1} cycles")
            log_state(dut, f"AT_{label.upper()}")
            return
    raise AssertionError(f"[FAIL] Did not reach {label} within {timeout_cycles} cycles")


async def wait_for_all_on(dut, timeout_cycles=400, label="all-on hit"):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if uo(dut) == ALL_ON:
            dut._log.info(f"[PASS] Reached {label} after {i+1} cycles")
            log_state(dut, "AT_HIT")
            return
    raise AssertionError(f"[FAIL] Did not reach {label} within {timeout_cycles} cycles")


async def wait_for_score_screen_visible(dut, timeout_cycles=250):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        val = uo(dut)
        if val != ALL_ON and val != expected_idle_output(0):
            dut._log.info(f"[PASS] Visible score-like screen after {i+1} cycles (0x{val:02X})")
            log_state(dut, "AT_SCORE")
            return
    raise AssertionError("[FAIL] Score screen not observed")


async def wait_for_hit_and_score(dut):
    if is_gatelevel(dut):
        await wait_for_all_on(dut, timeout_cycles=400, label="hit")
        await wait_for_score_screen_visible(dut, timeout_cycles=250)
        return

    await wait_for_state(dut, S_HIT, timeout_cycles=400, label="hit")
    assert uo(dut) == ALL_ON, f"[FAIL] HIT output should be 0xFF, got 0x{uo(dut):02X}"
    await wait_for_state(dut, S_SCORE, timeout_cycles=250, label="score")
    assert uo(dut) != ALL_ON, "[FAIL] SCORE screen should not remain all-on"


async def wait_for_dp_toggle_in_score(dut, timeout_cycles=300):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    seen0 = False
    seen1 = False

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)
        val = uo(dut)
        if val == ALL_ON:
            continue
        if has_bit(val, SEG_DP):
            seen1 = True
        else:
            seen0 = True
        if seen0 and seen1:
            dut._log.info(f"[PASS] DP toggled after {i+1} cycles")
            return

    raise AssertionError("[FAIL] DP did not toggle")


async def autoplay_until_score_increase(dut, timeout_cycles=1500):
    timeout_cycles = scaled_timeout(dut, timeout_cycles)
    if is_gatelevel(dut):
        raise AssertionError("[FAIL] autoplay_until_score_increase requires RTL-visible score")

    last_points = points_in_level(dut)

    for i in range(timeout_cycles):
        await RisingEdge(dut.clk)

        if state(dut) == S_RUN and obs_g(dut) == 1 and cooldown(dut) == 0:
            dut.ui_in.value = ui(dut) | 0x01
            await ClockCycles(dut.clk, 1)
            dut.ui_in.value = ui(dut) & ~0x01

        if points_in_level(dut) > last_points:
            dut._log.info(f"[PASS] Points increased from {last_points} to {points_in_level(dut)} after {i+1} cycles")
            return

    raise AssertionError("[FAIL] Could not increase points with autoplay")


@cocotb.test()
async def test_boot_idle(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    assert uo(dut) == expected_idle_output(0), f"[FAIL] Expected idle 0xBF, got 0x{uo(dut):02X}"
    if not is_gatelevel(dut):
        assert state(dut) == S_IDLE, f"[FAIL] Expected IDLE after reset, got {state(dut)}"
        assert points_in_level(dut) == 0, f"[FAIL] Points should reset to 0, got {points_in_level(dut)}"
        assert best_level_completed(dut) == 0, f"[FAIL] Best level should reset to 0, got {best_level_completed(dut)}"
        assert current_level(dut) == 0, f"[FAIL] Current level should reset to 0, got {current_level(dut)}"
    dut._log.info("[PASS] Boot idle test passed")


@cocotb.test()
async def test_start_and_motion(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_start_and_motion", "GL smoke skips motion timing check")
        return

    if not is_gatelevel(dut):
        assert state(dut) in (S_RUN, S_JUMP), f"[FAIL] Expected RUN/JUMP, got {state(dut)}"
    await wait_for_output_change(dut, timeout_cycles=120, label="gameplay motion")
    dut._log.info("[PASS] Start and motion test passed")


@cocotb.test()
async def test_hit_and_score_screen(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_hit_and_score_screen", "GL smoke skips long hit/score path")
        return

    await wait_for_hit_and_score(dut)
    await wait_for_dp_toggle_in_score(dut)
    dut._log.info("[PASS] Hit and score screen test passed")


@cocotb.test()
async def test_reset_from_gameplay(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut):
        await pulse_game_reset(dut, cycles=2)
        await ClockCycles(dut.clk, 10)
        assert has_bit(uo(dut), SEG_DP), f"[FAIL] Expected idle display with DP, got 0x{uo(dut):02X}"
        dut._log.info("[PASS] Reset from gameplay test passed")
        return

    await wait_for_output_change(dut, timeout_cycles=120, label="pre-reset gameplay activity")
    await pulse_game_reset(dut, cycles=2)
    await ClockCycles(dut.clk, 10)
    expected = expected_idle_output(best_level_completed(dut))
    assert state(dut) == S_IDLE, f"[FAIL] Reset from gameplay should go to IDLE, got {state(dut)}"
    assert current_level(dut) == 0, f"[FAIL] Reset from gameplay should clear current_level, got {current_level(dut)}"
    assert uo(dut) == expected, f"[FAIL] Reset from gameplay should show 0x{expected:02X}, got 0x{uo(dut):02X}"
    dut._log.info("[PASS] Reset from gameplay test passed")


@cocotb.test()
async def test_difficulty_modes(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_difficulty_modes", "difficulty divider not observable in GL netlist")
        return

    assert frame_period(dut) == 10, f"[FAIL] NORMAL frame_period should be 10, got {frame_period(dut)}"
    dut._log.info(f"[INFO] NORMAL frame_period={frame_period(dut)}")

    await apply_reset(dut, difficulty_bits=0b11, seed_bits=0b1111)
    assert frame_period(dut) == 4, f"[FAIL] INSANE frame_period should be 4, got {frame_period(dut)}"
    dut._log.info(f"[INFO] INSANE frame_period={frame_period(dut)}")
    dut._log.info("[PASS] Difficulty mode test passed")


@cocotb.test()
async def test_score_increment(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)
    await hold_jump_until_start(dut)

    if is_gatelevel(dut) and not is_gl_extended():
        gl_skip_lite(dut, "test_score_increment", "GL smoke skips autoplay score path")
        return

    await autoplay_until_score_increase(dut, timeout_cycles=1500)
    dut._log.info("[PASS] Score increment test passed")


@cocotb.test()
async def test_level_up_at_seven(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_level_up_at_seven", "requires RTL-visible internals")
        return

    dut_i(dut).state.value = S_JUMP
    dut_i(dut).points_in_level.value = 6
    dut_i(dut).best_level_completed.value = 0
    dut_i(dut).current_level.value = 0
    dut_i(dut).frame_period.value = 10
    dut_i(dut).difficulty_step.value = 2
    dut_i(dut).clk_div.value = 10
    dut_i(dut).obs_passed.value = 1
    dut_i(dut).obs_c.value = 0
    dut_i(dut).obs_g.value = 0
    dut_i(dut).obs_f.value = 0
    dut_i(dut).jump_timer.value = 7
    await settle()

    await step_clk(dut, 1)
    assert state(dut) == S_JUMP, f"[FAIL] Should stay in JUMP after level-up, got {state(dut)}"
    assert points_in_level(dut) == 0, f"[FAIL] Points should reset after reaching 7, got {points_in_level(dut)}"
    assert current_level(dut) == 1, f"[FAIL] Current level should increment to 1, got {current_level(dut)}"
    assert best_level_completed(dut) == 1, f"[FAIL] Best completed level should become 1, got {best_level_completed(dut)}"
    assert frame_period(dut) == 8, f"[FAIL] Difficulty should increase, frame_period should be 8, got {frame_period(dut)}"
    dut._log.info("[PASS] Level-up-at-seven test passed")


@cocotb.test()
async def test_level_persistence_after_reset(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_level_persistence_after_reset", "requires RTL-visible internals")
        return

    dut_i(dut).state.value = S_JUMP
    dut_i(dut).points_in_level.value = 6
    dut_i(dut).best_level_completed.value = 0
    dut_i(dut).current_level.value = 0
    dut_i(dut).frame_period.value = 10
    dut_i(dut).difficulty_step.value = 2
    dut_i(dut).clk_div.value = 10
    dut_i(dut).obs_passed.value = 1
    dut_i(dut).jump_timer.value = 7
    await settle()

    await step_clk(dut, 1)
    assert best_level_completed(dut) == 1, f"[FAIL] Expected best completed level to be 1, got {best_level_completed(dut)}"
    await pulse_game_reset(dut, cycles=2)
    await ClockCycles(dut.clk, 10)
    assert state(dut) == S_IDLE, f"[FAIL] Reset should go to IDLE, got {state(dut)}"
    assert current_level(dut) == 0, f"[FAIL] Current level should clear to 0, got {current_level(dut)}"
    assert uo(dut) == expected_idle_output(1), f"[FAIL] IDLE should show best level 1, got 0x{uo(dut):02X}"
    dut._log.info("[PASS] Level persistence test passed")


@cocotb.test()
async def test_win_sequence_7_flashes(dut):
    await start_clock(dut)
    await apply_reset(dut, difficulty_bits=0b00, seed_bits=0b1111)

    if is_gatelevel(dut):
        gl_skip_lite(dut, "test_win_sequence_7_flashes", "requires RTL-visible internals")
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

    await step_clk(dut, 1)
    assert state(dut) == S_WIN, f"[FAIL] Completing level 7 should enter WIN, got {state(dut)}"
    assert uo(dut) == WIN_ON, f"[FAIL] WIN should light all 7 segments, got 0x{uo(dut):02X}"

    flashes = 0
    prev_on = False
    for _ in range(200):
        now_on = (uo(dut) == WIN_ON)
        if now_on and not prev_on:
            flashes += 1
        prev_on = now_on
        if state(dut) == S_IDLE:
            break
        await step_clk(dut, 1)

    assert flashes == 7, f"[FAIL] WIN should flash 7 times, observed {flashes}"
    assert state(dut) == S_IDLE, f"[FAIL] WIN sequence should end in IDLE, got {state(dut)}"
    assert uo(dut) == expected_idle_output(7), f"[FAIL] After WIN idle should show 7, got 0x{uo(dut):02X}"
    dut._log.info("[PASS] Win sequence test passed")
