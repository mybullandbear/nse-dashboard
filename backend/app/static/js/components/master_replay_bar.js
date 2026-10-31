/**
 * Master Dashboard-Wide Historical Replay Controller (Zero Repetition)
 * Synchronizes the entire terminal (Radar, Confluence, Option Chain, Buildup Lab, Ticker Cards, Directional Bar)
 * to any recorded historical minute with zero duplicated code or disparate sliders.
 */
import { store, state } from '../state.js';
import { ApiClient } from '../api.js';

let _playInterval = null;

export function renderMasterReplayBar(containerId = 'master-replay-mount') {
  const mount = document.getElementById(containerId);
  if (!mount) return;

  const replayState = state.replay || { active: false, selectedDate: '2026-10-12', selectedTime: '09:15', speed: 1, isPlaying: false, availableDates: [], timeline: [] };
  const isReplay = Boolean(replayState.active);

  const dates = replayState.availableDates?.length ? replayState.availableDates : ['2026-10-12', '2026-10-09', '2026-10-08', '2026-10-07', '2026-10-06', '2026-10-05'];
  const curDate = replayState.selectedDate || dates[0];
  const curTime = replayState.selectedTime || '09:15';
  const timeline = replayState.timeline || [];
  const curIdx = timeline.length > 0 ? Math.max(0, timeline.indexOf(curTime)) : 0;
  const totalSteps = Math.max(1, timeline.length || 375);

  mount.innerHTML = `
    <div class="master-replay-card" style="
      background: linear-gradient(135deg, rgba(15, 23, 42, 0.95), rgba(30, 41, 59, 0.85));
      border: 1px solid ${isReplay ? 'rgba(139, 92, 246, 0.45)' : 'rgba(255, 255, 255, 0.08)'};
      border-radius: 10px;
      padding: 10px 16px;
      margin: 8px 0 12px 0;
      box-shadow: ${isReplay ? '0 0 20px rgba(139, 92, 246, 0.2)' : '0 4px 12px rgba(0,0,0,0.3)'};
      transition: all 0.3s ease;
    ">
      <!-- Top Row: Mode Switcher & Session Status -->
      <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; margin-bottom: ${isReplay ? '10px' : '0'};">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span style="font-size: 11px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: #94a3b8;">
            TERMINAL TELEMETRY ENGINE:
          </span>
          <div style="display: flex; background: rgba(0, 0, 0, 0.35); border-radius: 6px; padding: 2px; border: 1px solid rgba(255,255,255,0.06);">
            <button id="btn-mode-live" style="
              background: ${!isReplay ? '#10b981' : 'transparent'};
              color: ${!isReplay ? '#ffffff' : '#94a3b8'};
              border: none;
              border-radius: 5px;
              padding: 5px 12px;
              font-size: 11px;
              font-weight: 800;
              cursor: pointer;
              display: flex;
              align-items: center;
              gap: 6px;
              box-shadow: ${!isReplay ? '0 0 12px rgba(16,185,129,0.4)' : 'none'};
              transition: all 0.2s ease;
            ">
              <span style="display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: ${!isReplay ? '#ffffff' : '#10b981'}; animation: ${!isReplay ? 'pulse 1.5s infinite' : 'none'};"></span>
              ● LIVE STREAMING (FYERS PRIME)
            </button>
            <button id="btn-mode-replay" style="
              background: ${isReplay ? '#8b5cf6' : 'transparent'};
              color: ${isReplay ? '#ffffff' : '#94a3b8'};
              border: none;
              border-radius: 5px;
              padding: 5px 12px;
              font-size: 11px;
              font-weight: 800;
              cursor: pointer;
              display: flex;
              align-items: center;
              gap: 6px;
              box-shadow: ${isReplay ? '0 0 14px rgba(139,92,246,0.5)' : 'none'};
              transition: all 0.2s ease;
            ">
              <span>▶</span>
              WHOLE-DAY REPLAY (TIME-TRAVEL)
            </button>
          </div>
        </div>

        ${!isReplay ? `
          <div style="font-size: 11px; color: #38bdf8; font-family: monospace; display: flex; align-items: center; gap: 6px;">
            <span style="color: #10b981; font-weight: 700;">● ZERO-LATENCY STREAM</span>
            <span style="color: #64748b;">|</span>
            <span>Ticks: Active</span>
          </div>
        ` : `
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 10.5px; font-weight: 700; color: #c084fc; background: rgba(139, 92, 246, 0.15); border: 1px solid rgba(139, 92, 246, 0.35); padding: 3px 8px; border-radius: 4px;">
              🔒 ALL VIEWS SYNCHRONIZED
            </span>
            <span style="font-family: monospace; font-size: 12px; font-weight: 800; color: #f8fafc; background: #0f172a; padding: 3px 10px; border-radius: 4px; border: 1px solid #334155;">
              ⏰ ${curTime} IST
            </span>
          </div>
        `}
      </div>

      <!-- Bottom Replay Toolbar (Visible only in Replay Mode) -->
      ${isReplay ? `
        <div style="display: flex; flex-direction: column; gap: 10px; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06);">
          
          <!-- Controls Row: Date, Step Buttons, Play/Pause, Speed -->
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            
            <!-- Session Date Select -->
            <div style="display: flex; align-items: center; gap: 6px;">
              <span style="font-size: 11px; color: #94a3b8; font-weight: 700;">Session:</span>
              <select id="master-replay-date-select" style="
                background: #1e293b;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11.5px;
                font-weight: 700;
                cursor: pointer;
                outline: none;
              ">
                ${dates.map(d => `<option value="${d}" ${d === curDate ? 'selected' : ''}>${d}</option>`).join('')}
              </select>
            </div>

            <!-- Playback Control Buttons -->
            <div style="display: flex; align-items: center; gap: 4px;">
              <button class="replay-step-btn" id="btn-replay-start" title="Market Open (09:15)" style="background: #334155; color: #f8fafc; border: none; border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: 700; cursor: pointer;">⏮</button>
              <button class="replay-step-btn" id="btn-replay-prev" title="-1 Minute" style="background: #334155; color: #f8fafc; border: none; border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: 700; cursor: pointer;">◀ -1m</button>
              <button id="btn-replay-play" style="
                background: ${replayState.isPlaying ? '#ef4444' : '#8b5cf6'};
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 800;
                cursor: pointer;
                box-shadow: ${replayState.isPlaying ? '0 0 10px rgba(239,68,68,0.5)' : '0 0 10px rgba(139,92,246,0.5)'};
              ">
                ${replayState.isPlaying ? '⏸ PAUSE' : '▶ PLAY'}
              </button>
              <button class="replay-step-btn" id="btn-replay-next" title="+1 Minute" style="background: #334155; color: #f8fafc; border: none; border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: 700; cursor: pointer;">+1m ▶</button>
              <button class="replay-step-btn" id="btn-replay-end" title="Market Close (15:30)" style="background: #334155; color: #f8fafc; border: none; border-radius: 4px; padding: 4px 8px; font-size: 11px; font-weight: 700; cursor: pointer;">⏭</button>
            </div>

            <!-- Playback Speed -->
            <div style="display: flex; align-items: center; gap: 4px;">
              <span style="font-size: 10.5px; color: #94a3b8; font-weight: 700;">Speed:</span>
              ${[1, 2, 5].map(spd => `
                <button class="replay-speed-btn" data-speed="${spd}" style="
                  background: ${(replayState.speed || 1) === spd ? '#8b5cf6' : '#1e293b'};
                  color: ${(replayState.speed || 1) === spd ? '#ffffff' : '#94a3b8'};
                  border: 1px solid ${(replayState.speed || 1) === spd ? '#8b5cf6' : '#334155'};
                  border-radius: 4px;
                  padding: 2px 6px;
                  font-size: 10px;
                  font-weight: 700;
                  cursor: pointer;
                ">${spd}x</button>
              `).join('')}
            </div>

            <!-- Quick Jumps -->
            <div style="display: flex; align-items: center; gap: 4px;">
              <span style="font-size: 10px; color: #64748b; font-weight: 700;">JUMP:</span>
              <button class="replay-jump-chip" data-time="09:15" style="background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 4px; padding: 2px 5px; font-size: 10px; cursor: pointer;">Open</button>
              <button class="replay-jump-chip" data-time="10:00" style="background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 4px; padding: 2px 5px; font-size: 10px; cursor: pointer;">IB</button>
              <button class="replay-jump-chip" data-time="11:30" style="background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 4px; padding: 2px 5px; font-size: 10px; cursor: pointer;">Lunch</button>
              <button class="replay-jump-chip" data-time="13:30" style="background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 4px; padding: 2px 5px; font-size: 10px; cursor: pointer;">PM Move</button>
              <button class="replay-jump-chip" data-time="15:15" style="background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 4px; padding: 2px 5px; font-size: 10px; cursor: pointer;">Close</button>
            </div>
          </div>

          <!-- Timeline Scrubber Row -->
          <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 10.5px; font-family: monospace; color: #64748b;">09:15</span>
            <input type="range" id="master-replay-slider" min="0" max="${totalSteps - 1}" value="${curIdx}" style="
              flex: 1;
              accent-color: #8b5cf6;
              cursor: pointer;
              height: 6px;
              background: #334155;
              border-radius: 3px;
            ">
            <span style="font-size: 10.5px; font-family: monospace; color: #64748b;">15:30</span>
            <span style="font-size: 11px; font-weight: 800; font-family: monospace; color: #c084fc; min-width: 65px; text-align: right;">
              ${curTime} (${curIdx + 1}/${totalSteps})
            </span>
          </div>

        </div>
      ` : ''}
    </div>
  `;

  _attachListeners(mount);
}

function _attachListeners(mount) {
  // 1. Toggle Mode Buttons
  const liveBtn = mount.querySelector('#btn-mode-live');
  const replayBtn = mount.querySelector('#btn-mode-replay');

  if (liveBtn) {
    liveBtn.onclick = () => {
      _stopPlayback();
      const rState = { ...state.replay, active: false, isPlaying: false };
      store.setState({ replay: rState, dataSource: 'FYERS_LIVE' });
      renderMasterReplayBar();
      window.dispatchEvent(new CustomEvent('terminal:live-sync'));
    };
  }

  if (replayBtn) {
    replayBtn.onclick = async () => {
      const dates = state.replay?.availableDates?.length ? state.replay.availableDates : ['2026-10-12'];
      const curDate = state.replay?.selectedDate || dates[0];
      await scrubTo(curDate, state.replay?.selectedTime || '09:15', true);
    };
  }

  // 2. Date Selection
  const dateSelect = mount.querySelector('#master-replay-date-select');
  if (dateSelect) {
    dateSelect.onchange = async (e) => {
      const newDate = e.target.value;
      await scrubTo(newDate, '09:15', true);
    };
  }

  // 3. Slider Scrub
  const slider = mount.querySelector('#master-replay-slider');
  if (slider) {
    slider.oninput = (e) => {
      const idx = parseInt(e.target.value, 10);
      const timeline = state.replay?.timeline || [];
      if (timeline[idx]) {
        scrubTo(state.replay.selectedDate, timeline[idx], false);
      }
    };
  }

  // 4. Play / Pause Button
  const playBtn = mount.querySelector('#btn-replay-play');
  if (playBtn) {
    playBtn.onclick = () => {
      if (state.replay?.isPlaying) {
        _stopPlayback();
      } else {
        _startPlayback();
      }
    };
  }

  // 5. Step Buttons
  const prevBtn = mount.querySelector('#btn-replay-prev');
  if (prevBtn) {
    prevBtn.onclick = () => _stepMinute(-1);
  }
  const nextBtn = mount.querySelector('#btn-replay-next');
  if (nextBtn) {
    nextBtn.onclick = () => _stepMinute(1);
  }
  const startBtn = mount.querySelector('#btn-replay-start');
  if (startBtn) {
    startBtn.onclick = () => {
      const timeline = state.replay?.timeline || [];
      if (timeline.length) scrubTo(state.replay.selectedDate, timeline[0], false);
    };
  }
  const endBtn = mount.querySelector('#btn-replay-end');
  if (endBtn) {
    endBtn.onclick = () => {
      const timeline = state.replay?.timeline || [];
      if (timeline.length) scrubTo(state.replay.selectedDate, timeline[timeline.length - 1], false);
    };
  }

  // 6. Speed Buttons
  mount.querySelectorAll('.replay-speed-btn').forEach(btn => {
    btn.onclick = () => {
      const speed = parseInt(btn.dataset.speed, 10) || 1;
      const rState = { ...state.replay, speed };
      store.setState({ replay: rState });
      if (state.replay.isPlaying) {
        _stopPlayback();
        _startPlayback();
      } else {
        renderMasterReplayBar();
      }
    };
  });

  // 7. Quick Jump Chips
  mount.querySelectorAll('.replay-jump-chip').forEach(btn => {
    btn.onclick = () => {
      const targetTime = btn.dataset.time;
      const timeline = state.replay?.timeline || [];
      const match = timeline.find(t => t >= targetTime) || timeline[0];
      if (match) scrubTo(state.replay.selectedDate, match, false);
    };
  });
}

function _startPlayback() {
  _stopPlayback();
  const speed = state.replay?.speed || 1;
  const intervalMs = Math.max(200, Math.round(1000 / speed));

  const rState = { ...state.replay, isPlaying: true };
  store.setState({ replay: rState });
  renderMasterReplayBar();

  _playInterval = setInterval(() => {
    const timeline = state.replay?.timeline || [];
    if (!timeline.length) return;
    const curIdx = timeline.indexOf(state.replay.selectedTime);
    if (curIdx >= timeline.length - 1) {
      _stopPlayback();
      return;
    }
    const nextTime = timeline[curIdx + 1];
    scrubTo(state.replay.selectedDate, nextTime, false);
  }, intervalMs);
}

function _stopPlayback() {
  if (_playInterval) {
    clearInterval(_playInterval);
    _playInterval = null;
  }
  if (state.replay?.isPlaying) {
    const rState = { ...state.replay, isPlaying: false };
    store.setState({ replay: rState });
    renderMasterReplayBar();
  }
}

function _stepMinute(delta) {
  const timeline = state.replay?.timeline || [];
  if (!timeline.length) return;
  const curIdx = Math.max(0, timeline.indexOf(state.replay.selectedTime));
  const newIdx = Math.min(timeline.length - 1, Math.max(0, curIdx + delta));
  scrubTo(state.replay.selectedDate, timeline[newIdx], false);
}

export async function scrubTo(date, timeStr, fullRefresh = false) {
  try {
    const activeSym = state.activeSymbol || 'NIFTY';
    const res = await ApiClient.fetchUnifiedReplay(date, timeStr, activeSym);
    if (!res || !res.success) {
      console.warn('Replay snapshot failed:', res?.error);
      return;
    }

    const rState = {
      ...state.replay,
      active: true,
      selectedDate: res.trade_date,
      selectedTime: res.time_str,
      availableDates: res.available_dates || state.replay.availableDates,
      timeline: res.timeline || state.replay.timeline,
      snapshot: res
    };

    store.setState({
      replay: rState,
      dataSource: `REPLAY (${res.trade_date} ${res.time_str})`
    });

    renderMasterReplayBar();

    // Broadcast unified replay snapshot to all views
    window.dispatchEvent(new CustomEvent('terminal:replay-sync', { detail: res }));
  } catch (e) {
    console.error('Error scrubbing replay:', e);
  }
}

// Initial fetch of available sessions on boot
export async function initMasterReplay() {
  try {
    const res = await ApiClient.fetchUnifiedReplaySessions();
    if (res && res.success && res.available_dates) {
      const rState = {
        ...state.replay,
        availableDates: res.available_dates,
        selectedDate: res.default_date
      };
      store.setState({ replay: rState });
    }
  } catch (e) {
    console.debug('Error init master replay sessions:', e);
  }
  renderMasterReplayBar();
}
