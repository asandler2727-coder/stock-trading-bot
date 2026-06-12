import math
from datetime import datetime, timezone
import pandas as pd
from typing import Any
from stockslab import engine, metrics
from stockslab.strategies.base import RotationStrategy
from stockslab.data import UNIVERSE

def safe_pf(pf: float | None) -> tuple[float | None, bool]:
    if pf is None or math.isnan(pf):
        return None, False
    if math.isinf(pf):
        return None, True
    return pf, False

def get_instants(t_dt: pd.Timestamp, t_next_dt: pd.Timestamp | None, entry_at_open: bool, interval: str):
    if interval == "1d":
        bt = t_dt.tz_localize("America/New_York")
        da = t_dt.replace(hour=16, minute=0).tz_localize("America/New_York")
        
        if entry_at_open:
            dvf = t_dt.replace(hour=9, minute=30).tz_localize("America/New_York")
        else:
            if t_next_dt is not None:
                dvf = t_next_dt.replace(hour=9, minute=30).tz_localize("America/New_York")
            else:
                dvf = (t_dt + pd.Timedelta(days=1)).replace(hour=9, minute=30).tz_localize("America/New_York")
    else:
        bt = t_dt
        delta = pd.Timedelta(hours=1) if interval == "1h" else pd.Timedelta(minutes=5)
        da = t_dt + delta
        if entry_at_open:
            dvf = t_dt
        else:
            if t_next_dt is not None:
                dvf = t_next_dt
            else:
                dvf = t_dt + delta
                
    return bt.isoformat(), da.isoformat(), dvf.isoformat(), None

def build_backtest_result(
    strategy: Any,
    panel: dict[str, pd.DataFrame],
    trades: list[engine.Trade],
    run_metadata: dict[str, Any]
) -> dict[str, Any]:
    interval = run_metadata["interval"]
    entry_at_open = getattr(strategy, "entry_at_open", False)
    is_rotation = isinstance(strategy, RotationStrategy)
    live_capable = getattr(strategy, "live_capable", False)

    all_signals = []
    
    if is_rotation:
        all_dates = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in panel.values()])))
        holdings_df = strategy.target_holdings(panel, all_dates)
        req_inputs = getattr(strategy, "required_inputs", ["close"] if live_capable else None)
        
        for sym in holdings_df.columns:
            if sym not in panel:
                continue
            df = panel[sym]
            vals = holdings_df[sym].values
            prev = 0
            
            for i in range(len(holdings_df)):
                curr = int(vals[i])
                reb_date = holdings_df.index[i]
                future = df.index[df.index > reb_date]
                t_dt = reb_date
                t_next_dt = future[0] if len(future) > 0 else None
                
                if prev == 0 and curr == 1:
                    status = "skipped_in_backtest"
                    reason = "no_next_bar"
                    if len(future) > 0:
                        fill_date = future[0]
                        filled = any((t.entry_date == fill_date and t.symbol == sym) for t in trades)
                        if filled:
                            status = "filled_in_backtest"
                            reason = None
                        else:
                            reason = "already_in_position"
                    
                    bar_time, data_avail, dec_valid_from, dec_valid_until = get_instants(t_dt, t_next_dt, entry_at_open, interval)
                    sig_id = f"{strategy.name}:{sym}:{bar_time}:entry"
                    all_signals.append({
                        "signal_id": sig_id,
                        "symbol": sym,
                        "bar_time": bar_time,
                        "data_available_at": data_avail,
                        "signal_generated_at": data_avail,
                        "decision_valid_from": dec_valid_from,
                        "decision_valid_until": dec_valid_until,
                        "signal_type": "entry",
                        "side": "long",
                        "engine_signal_status": status,
                        "engine_skip_reason": reason,
                        "score": None,
                        "score_name": None,
                        "score_components": None,
                        "stop_dist": None,
                        "required_inputs": req_inputs,
                        "data_quality_flags": None
                    })
                elif prev == 1 and curr == 0:
                    bar_time, data_avail, dec_valid_from, dec_valid_until = get_instants(t_dt, t_next_dt, entry_at_open, interval)
                    sig_id = f"{strategy.name}:{sym}:{bar_time}:exit"
                    all_signals.append({
                        "signal_id": sig_id,
                        "symbol": sym,
                        "bar_time": bar_time,
                        "data_available_at": data_avail,
                        "signal_generated_at": data_avail,
                        "decision_valid_from": dec_valid_from,
                        "decision_valid_until": dec_valid_until,
                        "signal_type": "exit",
                        "side": "long",
                        "engine_signal_status": "exit_only",
                        "engine_skip_reason": None,
                        "score": None,
                        "score_name": None,
                        "score_components": None,
                        "stop_dist": None,
                        "required_inputs": req_inputs,
                        "data_quality_flags": None
                    })
                prev = curr
    else:
        req_inputs = getattr(strategy, "required_inputs", ["close"] if live_capable else None)
        for sym, df in panel.items():
            signals_df = strategy.generate(df)
            entry_long = signals_df["entry_long"].values.astype(bool)
            exit_long = signals_df["exit_long"].values.astype(bool)
            stop_dist_arr = signals_df["stop_dist"].values.astype(float)
            n_bars = len(df)
            
            for i in range(n_bars):
                t_dt = df.index[i]
                t_next_dt = df.index[i + 1] if i + 1 < n_bars else None
                bar_time, data_avail, dec_valid_from, dec_valid_until = get_instants(t_dt, t_next_dt, entry_at_open, interval)
                
                if entry_long[i]:
                    sd = stop_dist_arr[i]
                    status = "skipped_in_backtest"
                    reason = None
                    fill_date = t_dt if entry_at_open else t_next_dt
                    
                    if math.isnan(sd) or sd <= 0.0:
                        reason = "invalid_stop_dist"
                    elif not entry_at_open and i + 1 == n_bars:
                        reason = "no_next_bar"
                    else:
                        filled = any((t.entry_date == fill_date and t.symbol == sym) for t in trades)
                        if filled:
                            status = "filled_in_backtest"
                        else:
                            reason = "already_in_position"
                    
                    sig_id = f"{strategy.name}:{sym}:{bar_time}:entry"
                    all_signals.append({
                        "signal_id": sig_id,
                        "symbol": sym,
                        "bar_time": bar_time,
                        "data_available_at": data_avail,
                        "signal_generated_at": data_avail,
                        "decision_valid_from": dec_valid_from,
                        "decision_valid_until": dec_valid_until,
                        "signal_type": "entry",
                        "side": "long",
                        "engine_signal_status": status,
                        "engine_skip_reason": reason,
                        "score": None,
                        "score_name": None,
                        "score_components": None,
                        "stop_dist": None if math.isnan(sd) else float(sd),
                        "required_inputs": req_inputs,
                        "data_quality_flags": None
                    })
                    
                if exit_long[i]:
                    sig_id = f"{strategy.name}:{sym}:{bar_time}:exit"
                    all_signals.append({
                        "signal_id": sig_id,
                        "symbol": sym,
                        "bar_time": bar_time,
                        "data_available_at": data_avail,
                        "signal_generated_at": data_avail,
                        "decision_valid_from": dec_valid_from,
                        "decision_valid_until": dec_valid_until,
                        "signal_type": "exit",
                        "side": "long",
                        "engine_signal_status": "exit_only",
                        "engine_skip_reason": None,
                        "score": None,
                        "score_name": None,
                        "score_components": None,
                        "stop_dist": None,
                        "required_inputs": req_inputs,
                        "data_quality_flags": None
                    })

    # Maps (symbol, decision_valid_from_naive_normalized) to signal_id
    entry_signal_map = {}
    for sig in all_signals:
        if sig["signal_type"] == "entry" and sig["engine_signal_status"] == "filled_in_backtest":
            sig_ts = pd.Timestamp(sig["decision_valid_from"])
            if sig_ts.tz is not None and interval == "1d":
                sig_ts = sig_ts.tz_localize(None).normalize()
            entry_signal_map[(sig["symbol"], sig_ts)] = sig["signal_id"]

    out_trades = []
    for t in trades:
        t_entry_norm = t.entry_date.normalize() if interval == "1d" else t.entry_date
        out_trades.append({
            "symbol": t.symbol,
            "source_signal_id": entry_signal_map.get((t.symbol, t_entry_norm), None),
            "entry_date": pd.Timestamp(get_instants(t.entry_date, None, False, interval)[0]).isoformat(),
            "exit_date": pd.Timestamp(get_instants(t.exit_date, None, False, interval)[0]).isoformat(),
            "entry": t.entry,
            "exit": t.exit,
            "shares": t.shares,
            "r_multiple": t.r_multiple,
            "pct_return": t.pct_return,
            "exit_reason": t.exit_reason
        })

    # Risk stats
    summary = metrics.summarize(trades) if trades else {}
    pf, is_inf = safe_pf(summary.get("pf"))
    
    all_sym_dates = []
    for df in panel.values():
        all_sym_dates.extend(df.index)
    if all_sym_dates:
        start_dt = min(all_sym_dates)
        end_dt = max(all_sym_dates)
        start_str = start_dt.isoformat()
        end_str = end_dt.isoformat()
    else:
        start_str = "1970-01-01"
        end_str = "1970-01-01"

    per_symbol_stats = {}
    for sym in panel.keys():
        sym_trades = [t for t in trades if t.symbol == sym]
        if sym_trades:
            s_sum = metrics.summarize(sym_trades)
            s_pf, s_inf = safe_pf(s_sum.get("pf"))
            per_symbol_stats[sym] = {
                "trade_count": s_sum.get("n", 0),
                "win_rate": s_sum.get("wr", 0.0),
                "expectancy_R": s_sum.get("avg_r", 0.0),
                "profit_factor": s_pf,
                "profit_factor_is_infinite": s_inf
            }

    data_quality_flags = []
    data_quality_flags.append("adjusted_prices")
    if interval in ["1h", "5m"]:
        data_quality_flags.append("thin_intraday_history")
        data_quality_flags.append("intraday_bar_label_unconfirmed")
    if any(UNIVERSE.get(s, {}).get("kind") == "stock" for s in panel.keys()):
        data_quality_flags.append("survivorship_bias_stocks")

    caveats = ["prices_adjusted"]
    if interval in ["1h", "5m"]:
        caveats.extend(["intraday_bar_label_convention", "thin_intraday_history"])
    if any(UNIVERSE.get(s, {}).get("kind") == "stock" for s in panel.keys()):
        caveats.append("survivorship_bias_stocks")
    caveats.append("long_only_engine")
    if is_rotation:
        caveats.append("Rotation strategy uses R-proxy based on notional 10% move")

    gate_p1, gate_p1_reasons = metrics.phase1_gate(summary) if summary else (False, ["No trades"])
    gate_p2, gate_p2_reasons = metrics.phase2_oos(summary) if summary else (False, ["No trades"])
    
    # We shouldn't set evaluation to true if we didn't run that split.
    res = {
        "result_contract_version": "0.2.0",
        "run_id": run_metadata["run_id"],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repo_commit": run_metadata["repo_commit"],
        "payload_type": "backtest_result",
        "strategy": {
            "name": strategy.name,
            "version": getattr(strategy, "version", None),
            "kind": "rotation" if is_rotation else "signal",
            "timeframe": strategy.timeframe,
            "universe_label": strategy.universe,
            "live_capable": live_capable,
            "params": strategy.params,
            "config": {
                "target_r": getattr(strategy, "target_r", None),
                "trail_atr_mult": getattr(strategy, "trail_atr_mult", None),
                "time_stop_bars": getattr(strategy, "time_stop_bars", None),
                "session_exit": getattr(strategy, "session_exit", False),
                "entry_at_open": entry_at_open
            }
        },
        "symbols": list(panel.keys()),
        "data": {
            "source": "yfinance",
            "adjustment": "split_dividend_adjusted",
            "interval": interval,
            "timezone": "America/New_York" if interval in ["1h", "5m"] else "naive",
            "range": {
                "start": start_str,
                "end": end_str
            },
            "split_label": run_metadata["split_label"],
            "live_price_required_for_sizing": True,
            "bars_per_symbol": {sym: len(df) for sym, df in panel.items()}
        },
        "sim_assumptions": {
            "engine_semantics_version": "1.0",
            "slippage_model": {
                "type": "per_side_bps_by_tier",
                "tiers_bps": {str(k): float(v) for k, v in engine.TIER_BPS.items()},
                "applied": "both_sides",
                "symbol_tier": {sym: int(UNIVERSE.get(sym, {"tier": 3}).get("tier", 3)) for sym in panel.keys()}
            },
            "commission_model": {
                "type": "none",
                "per_trade": 0.0
            },
            "fill_model": {
                "semantics_version": "1.0",
                "entry": "same_bar_open" if entry_at_open else "next_bar_open",
                "entry_ref": "open",
                "exit_priority": ["rotation", "eod"] if is_rotation else ["gap_stop", "stop", "target", "signal", "time", "session", "eod"],
                "stop_before_target": True,
                "gap_through_stop_fills_at": "open",
                "one_position_per_symbol": True,
                "pyramiding": False
            },
            "sizing_model": {
                "type": "fixed_unit_R",
                "risk_per_trade_R": 1.0,
                "equity_curve_risk_frac": 0.01,
                "dollar_sizing": "not_modeled"
            },
            "calendar_assumptions": {
                "trading_calendar": "yfinance_native",
                "session_boundary": "calendar_day_change_in_index"
            }
        },
        "signals": all_signals,
        "empirical_risk_stats": {
            "trade_count": int(summary.get("n", 0)),
            "win_rate": float(summary.get("wr", 0.0)),
            "expectancy_R": float(summary.get("avg_r", 0.0)),
            "profit_factor": pf,
            "profit_factor_is_infinite": is_inf,
            "max_drawdown_frac": float(summary.get("max_dd_1pct", 0.0)),
            "median_hold_days": float(summary.get("med_hold_bars", 0.0)),
            "exit_reason_counts": {str(k): int(v) for k, v in summary.get("exit_reason_counts", {}).items()}
        },
        "data_quality": {
            "status": "warning" if interval in ["1h", "5m"] else "ok",
            "flags": data_quality_flags
        },
        "caveats": caveats
    }
    
    if out_trades:
        res["trades"] = out_trades
        
    # Optional fields in empirical_risk_stats
    for k, mk in [("avg_winner_R", "avg_win_r"), ("avg_loser_R", "avg_loss_r"), 
                  ("worst_trade_R", "min_r"), ("best_trade_R", "max_r"),
                  ("worst_trade_pct", "min_pct"), ("best_trade_pct", "max_pct")]:
        if mk in summary and not math.isnan(summary[mk]):
            res["empirical_risk_stats"][k] = float(summary[mk])
            
    if per_symbol_stats:
        res["per_symbol_stats"] = per_symbol_stats

    res["research_status"] = {
        "phase1_gate": {
            "evaluated": run_metadata["split_label"] == "IS",
            "passed": bool(gate_p1) if run_metadata["split_label"] == "IS" else None,
            "reasons": gate_p1_reasons if run_metadata["split_label"] == "IS" else []
        },
        "phase2_oos": {
            "evaluated": run_metadata["split_label"] == "OOS",
            "passed": bool(gate_p2) if run_metadata["split_label"] == "OOS" else None,
            "reasons": gate_p2_reasons if run_metadata["split_label"] == "OOS" else []
        }
    }
    
    return res
