`default_nettype none

module tt_um_dino7 (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    assign uio_out = 8'b0;
    assign uio_oe  = 8'b0;

    wire unused_ok = &{ena, uio_in, 1'b0};

    wire jump_btn = ui_in[0];
    wire game_rst = ui_in[1];
    wire [1:0] difficulty = ui_in[3:2];
    wire [3:0] seed = ui_in[7:4];

    reg [31:0] lfsr;

    localparam S_IDLE  = 3'd0;
    localparam S_RUN   = 3'd1;
    localparam S_JUMP  = 3'd2;
    localparam S_HIT   = 3'd3;
    localparam S_SCORE = 3'd4;
    localparam S_WIN   = 3'd5;

    reg [2:0] state;
    reg [3:0] points_in_level;
    reg [3:0] best_level_completed;
    reg [2:0] current_level;

    reg [23:0] clk_div;
    reg [23:0] frame_period;
    reg [23:0] difficulty_step;
    wire frame_tick = (clk_div >= frame_period);

    reg obs_c, obs_g, obs_f, obs_passed;
    reg [2:0] jump_timer;
    reg [2:0] cooldown_timer;
    reg [4:0] flash_timer;
    reg [3:0] victory_flash_phase;

    reg [23:0] base_frame_period;
    reg [23:0] base_difficulty_step;

    always @(difficulty) begin
        `ifdef COCOTB_SIM
            case (difficulty)
                2'b00: begin base_frame_period = 24'd10; base_difficulty_step = 24'd2; end
                2'b01: begin base_frame_period = 24'd8;  base_difficulty_step = 24'd2; end
                2'b10: begin base_frame_period = 24'd6;  base_difficulty_step = 24'd1; end
                default: begin base_frame_period = 24'd4; base_difficulty_step = 24'd1; end
            endcase
        `else
            case (difficulty)
                2'b00: begin base_frame_period = 24'd6_250_000; base_difficulty_step = 24'd1_000_000; end
                2'b01: begin base_frame_period = 24'd5_000_000; base_difficulty_step = 24'd1_000_000; end
                2'b10: begin base_frame_period = 24'd3_750_000; base_difficulty_step = 24'd800_000;   end
                default: begin base_frame_period = 24'd2_500_000; base_difficulty_step = 24'd500_000; end
            endcase
        `endif
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= S_IDLE;
            clk_div <= 0;
            points_in_level <= 0;
            best_level_completed <= 0;
            current_level <= 0;
            obs_c <= 0;
            obs_g <= 0;
            obs_f <= 0;
            obs_passed <= 0;
            jump_timer <= 0;
            cooldown_timer <= 0;
            lfsr <= {28'hA5A5A5A, seed};
            frame_period <= base_frame_period;
            difficulty_step <= base_difficulty_step;
            flash_timer <= 0;
            victory_flash_phase <= 0;
        end else if (game_rst) begin
            state <= S_IDLE;
            clk_div <= 0;
            points_in_level <= 0;
            current_level <= 0;
            obs_c <= 0;
            obs_g <= 0;
            obs_f <= 0;
            obs_passed <= 0;
            jump_timer <= 0;
            cooldown_timer <= 0;
            lfsr <= {lfsr[27:0], seed};
            frame_period <= base_frame_period;
            difficulty_step <= base_difficulty_step;
            flash_timer <= 0;
            victory_flash_phase <= 0;
        end else begin
            clk_div <= clk_div + 1'b1;

            if (state == S_IDLE && jump_btn) begin
                state <= S_RUN;
            end

            if (state == S_RUN && jump_btn && cooldown_timer == 0) begin
                state <= S_JUMP;
                jump_timer <= 3;
            end

            if (frame_tick) begin
                clk_div <= 0;
                lfsr <= {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};

                case (state)
                    S_IDLE: begin
                    end

                    S_RUN, S_JUMP: begin
                        obs_passed <= obs_f;
                        obs_f <= obs_g;
                        obs_g <= obs_c;
                        obs_c <= (lfsr[0] & lfsr[1] & lfsr[2]) & !obs_c & !obs_g;

                        if (obs_f && state == S_RUN) begin
                            state <= S_HIT;
                            flash_timer <= 5;
                        end else if (obs_passed && state == S_JUMP) begin
                            if (points_in_level == 4'd6) begin
                                if (current_level == 3'd6) begin
                                    points_in_level <= 4'd7;
                                    if (best_level_completed < 4'd7)
                                        best_level_completed <= 4'd7;
                                    state <= S_WIN;
                                    flash_timer <= 0;
                                    victory_flash_phase <= 0;
                                end else begin
                                    points_in_level <= 0;
                                    current_level <= current_level + 1'b1;
                                    if (best_level_completed < ({1'b0, current_level} + 4'd1))
                                        best_level_completed <= ({1'b0, current_level} + 4'd1);
                                    if (frame_period > base_difficulty_step)
                                        frame_period <= frame_period - base_difficulty_step;
                                end
                            end else begin
                                points_in_level <= points_in_level + 1'b1;
                            end
                        end

                        if (state == S_JUMP) begin
                            if (jump_timer > 0) begin
                                jump_timer <= jump_timer - 1'b1;
                            end else if (!(obs_passed && points_in_level == 4'd6 && current_level == 3'd6)) begin
                                state <= S_RUN;
                                cooldown_timer <= 3'd2;
                            end
                        end else if (cooldown_timer > 0) begin
                            cooldown_timer <= cooldown_timer - 1'b1;
                        end
                    end

                    S_HIT: begin
                        if (flash_timer > 0)
                            flash_timer <= flash_timer - 1'b1;
                        else
                            state <= S_SCORE;
                    end

                    S_SCORE: begin
                        flash_timer <= flash_timer + 1'b1;
                    end

                    S_WIN: begin
                        if (flash_timer > 0) begin
                            flash_timer <= flash_timer - 1'b1;
                        end else begin
                            flash_timer <= 5;
                            if (victory_flash_phase < 4'd13) begin
                                victory_flash_phase <= victory_flash_phase + 1'b1;
                            end else begin
                                state <= S_IDLE;
                                points_in_level <= 0;
                                current_level <= 0;
                                obs_c <= 0;
                                obs_g <= 0;
                                obs_f <= 0;
                                obs_passed <= 0;
                                jump_timer <= 0;
                                cooldown_timer <= 0;
                                frame_period <= base_frame_period;
                                difficulty_step <= base_difficulty_step;
                                flash_timer <= 0;
                                victory_flash_phase <= 0;
                            end
                        end
                    end

                    default: state <= S_IDLE;
                endcase
            end
        end
    end

    function [6:0] seg7;
        input [3:0] val;
        begin
            case (val)
                0: seg7 = 7'b0111111;
                1: seg7 = 7'b0000110;
                2: seg7 = 7'b1011011;
                3: seg7 = 7'b1001111;
                4: seg7 = 7'b1100110;
                5: seg7 = 7'b1101101;
                6: seg7 = 7'b1111101;
                7: seg7 = 7'b0000111;
                8: seg7 = 7'b1111111;
                9: seg7 = 7'b1101111;
                default: seg7 = 7'b0000000;
            endcase
        end
    endfunction

    reg [7:0] out;
    always @(*) begin
        if (state == S_IDLE) begin
            out = {1'b1, seg7(best_level_completed)};
        end else if (state == S_HIT) begin
            out = 8'b11111111;
        end else if (state == S_WIN) begin
            if (victory_flash_phase[0] == 1'b0)
                out = 8'b01111111;
            else
                out = 8'b00000000;
        end else if (state == S_SCORE) begin
            if (flash_timer[3])
                out = {1'b1, seg7(best_level_completed)};
            else
                out = {1'b0, seg7(points_in_level)};
        end else begin
            out[0] = obs_c;
            out[1] = obs_g;
            out[2] = (state == S_RUN);
            out[3] = obs_passed;
            out[4] = (state == S_JUMP);
            out[5] = unused_ok;
            out[6] = obs_f;
            out[7] = (cooldown_timer > 0);
        end
    end

    assign uo_out = out;

endmodule
