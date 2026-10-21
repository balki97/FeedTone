(function () {
    'use strict';
    if (window.__feedToneLoaded) return;
    window.__feedToneLoaded = true;
    const storageKey = 'feedtone_enabled';
    const inputGateKey = 'feedtone_input_gate';
    let inputGateRestored = false;
    const providerId = 'feedtone';
    const executorId = 'feedtone-native';
    const routeKey = 'desktop-main';
    const sourceKey = value => typeof value === 'string'
        ? value.split('\0')[0].replace(/[A-Z]/g, c => c.toLowerCase()) : null;
    let enabled = false;
    try { enabled = localStorage.getItem(storageKey) === 'true'; } catch (_) {}
    let revision = 0, sequence = 0;
    let song = null, filename = '', pending = null;
    let active = '', requested = '', loading = false, committing = false;
    let host = null, restored = false;
    let designerPreview = false;
    let playing = null;
    let nativeBank = null;
    const presentation = { bound: false, overlay: null, liveIdentity: null };
    const listening = { bound: false, scope: '', generation: 0, ranges: [], range: null, busy: false, songVolume: null, gain: null };
    const designer = { bound: false, catalog: null, rigs: [], song: null, file: '', draft: null,
        context: null, dirty: false, version: 0, busy: false, live: null, rigId: null, selectedSlot: null };
    const preview = {active:false, playing:false, position:0, loaded:'', generation:0, native:false};
    let previewTimer = null;
    const requests = new Map();
    let state = 'Disabled. Open a converted FeedPak to inspect its original tones.';
    let coverageText = '';
    const desktop = () => window.feedBackDesktop?.audio || window.slopsmithDesktop?.audio;
    const route = () => host?.inspectRoute({ routeKey })?.payload?.route;
    const ownsRoute = () => route()?.providerId === providerId;
    const element = id => document.getElementById(id);
    function invalidate() { revision++; active = requested = ''; requests.clear(); nativeBank = null; }
    function render() {
        const toggle = element('feedtone-enabled');
        if (toggle && !toggle.dataset.bound) {
            toggle.dataset.bound = '1';
            toggle.addEventListener('change', async () => {
                designerPreview = false; designer.live = null;
                enabled = toggle.checked;
                try { localStorage.setItem(storageKey, String(enabled)); } catch (_) {}
                invalidate();
                if (enabled) {
                    if (!registerHost()) return;
                    const selected = host.selectChain({ routeKey, providerId, authorization: 'user-action' }, 'feedtone');
                    if (selected.outcome !== 'handled') { say(selected.reason); return; }
                    
                    restored = true;
                    say('Following this song’s original tones.');
                    if (!song) filename = '';
                    refresh(); follow();
                } else {
                    await updateSectionMix();
                    if (ownsRoute()) await host.releaseRoute({ routeKey, authorization: 'user-action' }, 'feedtone');
                    say('Disabled. The current audio chain is retained.');
                }
            });
        }
        if (toggle) toggle.checked = enabled && !designerPreview;
        if (element('ft-follow-control')) element('ft-follow-control').hidden = !inPlayer();
        if (element('ft-song-browser')) element('ft-song-browser').hidden = !!presentation.overlay;
        if (element('rst-resume')) element('rst-resume').hidden = !inPlayer();
        const label = element('feedtone-state');
        if (label) label.textContent = displayName(state);
        const coverage = element('feedtone-coverage');
        if (coverage) coverage.textContent = displayName(coverageText);
        bindDesigner();
        bindListening();
        bindPresentation();
    }
    function say(value) { state = value; render(); }
    async function api(path, options) {
        const response = await fetch('/api/plugins/feedtone/' + path, options);
        const body = await response.json();
        if (!response.ok) {
            const detail = body.detail;
            throw new Error(typeof detail === 'string' ? detail : (detail && detail.message) || `Request failed (${response.status})`);
        }
        return body;
    }
    function inPlayer() { return !!element('player')?.getBoundingClientRect().width; }
    function clock() { return preview.active && !inPlayer() ? preview.position : Number(window.highway?.getTime?.()); }
    function following() { return enabled || preview.active && !inPlayer(); }
    function current() { return preview.active && !inPlayer() ? {filename:designer.file, arrangement:element('rst-arrangement').value} : window.feedBack?.currentSong || {}; }
    function arrangement() {
        if (!song) return null;
        const now = current();
        const exact = song.arrangements.filter(a => a.id === now.arrangement || a.name === now.arrangement);
        if (exact.length === 1) return exact[0];
        const index = now.arrangementIndex;
        // The host's manifest index identifies the original arrangement even when its displayed name differs.
        if (Number.isInteger(index) && index >= 0 && index < song.arrangements.length) return song.arrangements[index];
        return null;
    }
    async function refresh() {
        const file = String(current().filename || current().file || '');
        if (!file || file === filename || file === pending?.file) return;
        const token = ++revision;
        song = null;
        active = requested = '';
        pending = { file, token };
        try {
            const loaded = await api('song?filename=' + encodeURIComponent(file));
            if (token !== revision || file !== String(current().filename || current().file || '')) return;
            song = loaded;
            filename = file;
            await syncDesignerSong();
            say(enabled ? 'Original tone metadata loaded.' : 'Original tone metadata loaded. Enable following to use supported tones.');
        } catch (error) {
            if (token === revision) { filename = file; say(error.message); }
        } finally {
            if (pending?.token === token) pending = null;
        }
        follow();
    }
    function originalToneAt(arrangement) {
        const time = clock();
        let key = arrangement.base;
        let latest = -Infinity;
        if (Number.isFinite(time)) {
            for (const change of arrangement.changes) {
                const when = Number(change.t);
                if (when <= time && when >= latest) { latest = when; key = change.name || change.rig; }
            }
        }
        return key;
    }
    function sectionAt() {
        if (listening.scope !== listeningScope()) return null;
        const time = clock();
        return [...listening.ranges].reverse().find(item => time >= item.start && time < item.end) || null;
    }
    function toneAt(arrangement) { return sectionAt()?.tone_key || originalToneAt(arrangement); }
    function valid(request) {
        const currentRequest = Date.now() < request.deadline && ownsRoute()
            && requests.get(request.id) === request && request.revision === revision;
        return currentRequest && (request.sectionRig
            ? following() && !designerPreview && arrangement()?.id === request.arrangementId && sectionAt()?.rig_id === request.sectionRig
            : request.customDefinition
            ? designerPreview && request.draftRevision === designer.version
            : following() && !designerPreview && arrangement()?.id === request.arrangementId && toneAt(arrangement()) === request.key);
    }
    function requireCurrent(request) {
        if (!valid(request)) throw new Error('The original tone request became stale.');
    }
    function hostSettings() {
        const number = id => {
            const node = element(id), value = node ? Number(node.value) : NaN;
            if (!Number.isFinite(value)) throw new Error('FeedBack audio controls are not ready; the chain is retained.');
            return value;
        };
        const gate = element('ae-noise-gate-enable'), polish = element('ae-tone-polish-enable');
        if (!gate || !polish) throw new Error('FeedBack tone controls are unavailable; the chain is retained.');
        return { outputGain: Math.pow(10, number('ae-output-gain') / 20),
            noiseGate: { enabled: !!gate.checked, thresholdDb: number('ae-noise-gate-threshold'),
                releaseMs: number('ae-noise-gate-release'), depthDb: number('ae-noise-gate-depth') },
            tonePolish: { enabled: !!polish.checked } };
    }
    function inputGateForLoad(current) {
        if (!inputGateRestored) {
            try {
                const saved = JSON.parse(localStorage.getItem(inputGateKey));
                if (saved && typeof saved.enabled === 'boolean'
                    && [['thresholdDb', -96, 0], ['releaseMs', 5, 2000], ['depthDb', -100, 0]]
                        .every(([key, min, max]) => Number.isFinite(saved[key]) && saved[key] >= min && saved[key] <= max)) return saved;
            } catch (_) {}
        }
        return current;
    }
    async function applyHostSettings(settings, check) {
        // Host input gain, device selection, and master volume are deliberately untouched.
        const audio = desktop();
        if (check) check();
        window._aeApplyPresetNoiseGate(settings);
        window._aeApplyPresetTonePolish(settings);
        await audio.setNoiseGate(settings.noiseGate);
        if (check) check();
        await audio.setTonePolish(settings.tonePolish);
        if (check) check();
        await audio.setGain('chain', settings.outputGain);
        const db = 20 * Math.log10(settings.outputGain);
        const slider = element('ae-output-gain'), label = element('ae-output-gain-label');
        if (slider) slider.value = String(db);
        if (label) label.textContent = `${db.toFixed(1)} dB`;
    }
    function compatibleHost() {
        const audio = desktop();
        return ['savePreset', 'clearChain', 'loadPreset', 'getChainState', 'setNoiseGate', 'setTonePolish', 'setGain']
            .every(name => typeof audio?.[name] === 'function')
            && typeof window._aeApplyPresetNoiseGate === 'function'
            && typeof window._aeApplyPresetTonePolish === 'function';
    }
    function presetIsComplete(value) {
        const chain = value?.chain;
        return Array.isArray(chain) && chain.length === 1 && chain[0].type === 0
            && chain[0].rs_gear === 'feedtone-tone' && typeof chain[0].path === 'string'
            && /(?:^|[\\/])FeedTone\.vst3$/i.test(chain[0].path)
            && typeof chain[0].state === 'string' && chain[0].state.length > 0;
    }
    const bankKey = request => request.sectionRig ? 'rig:' + request.sectionRig : 'tone:' + request.toneKey;
    function usePayload(request, payload) {
        if (!presetIsComplete(payload.native_preset)) throw new Error('The engine returned an incomplete standalone VST preset.');
        request.prepared = payload.native_preset;
        request.controls = [...(payload.coverage?.controls || []), ...(payload.coverage?.volume_control ? [payload.coverage.volume_control] : [])];
        request.edited = !!payload.has_override;
        request.balance = payload.balance;
        request.definition = payload.definition || request.customDefinition;
    }
    async function prepareRequest(request) {
        return api(request.customDefinition ? 'designer/prepare' : 'preset', post(request.customDefinition
            ? { ...request.sourceContext, definition: request.customDefinition, title: request.label }
            : { filename: request.filename, arrangement_id: request.arrangementId, tone_key: request.toneKey }));
    }
    async function prepareBank(request) {
        const arr = arrangement();
        const candidates = new Map([[bankKey(request), request]]);
        for (const tone of arr.tone_plans || []) if (tone.plan.renderable) candidates.set('tone:' + tone.tone_key, {
            filename: request.filename, arrangementId: arr.id, toneKey: tone.tone_key });
        for (const section of listening.ranges) if (section.rig_id) {
            const rig = designer.rigs.find(item => item.id === section.rig_id);
            if (rig) candidates.set('rig:' + rig.id, { customDefinition: rig.definition, sourceContext: { rig_id: rig.id, song_filename:filename }, label: rig.name });
        }
        // shortcut: cap resident engines at 16; larger custom banks need a shared multi-tone service.
        if (candidates.size > 16) return [{ key: bankKey(request), candidate: request, payload: await prepareRequest(request) }];
        const entries = [];
        say('Preparing this arrangement’s tones before playback…');
        for (const [key, candidate] of candidates) {
            let payload;
            try { payload = await prepareRequest(candidate); }
            catch (error) {
                // A broken unused definition must not block a supported active tone.
                if (key === bankKey(request)) throw error;
                continue;
            }
            requireCurrent(request);
            if (presetIsComplete(payload.native_preset)) entries.push({ key, payload, candidate });
        }
        if (!entries.some(item => item.key === bankKey(request))) throw new Error('The active tone could not be prepared.');
        return entries;
    }
    async function resolveRequest(context) {
        const request = requests.get(context.target?.requestId);
        if (!request || !valid(request)) return { outcome: 'stale', reason: 'Original tone request is no longer current.' };
        if (!compatibleHost()) return { outcome: 'unavailable', reason: 'This FeedBack version lacks the required desktop audio transaction APIs. The current chain is retained.' };
        try {
            const device=await desktop().getCurrentDevice?.();
            if(device?.sampleRate && ![44100,48000].includes(device.sampleRate)) throw new Error('FeedTone supports 44.1 or 48 kHz. Change the audio sample rate before loading a rig.');
            requireCurrent(request);
            if (!request.prepared) {
                let payload;
                if (!designerPreview && typeof desktop().setMultiBypass === 'function') {
                    const entry = nativeBank?.revision === revision && nativeBank.entries.find(item => item.key === bankKey(request));
                    if (entry) { payload = entry.payload; request.reuseBank = nativeBank; }
                    else {
                        request.bankEntries = await prepareBank(request);
                        payload = request.bankEntries.find(item => item.key === bankKey(request)).payload;
                    }
                } else payload = await prepareRequest(request);
                requireCurrent(request);
                usePayload(request, payload);
            }
            return { outcome: 'handled', plan: { schema: host.planSchema, planId: `feedtone-plan-${request.id}`,
                providerId, routeKey, stages: [{ stageId: 'original-tone', kind: 'vst', role: 'utility', assetRef: 'feedtone-engine' }],
                summary: { source: 'feedpak-original-tone', stages: 1 } },
                assets: { 'feedtone-engine': { requestId: request.id } } };
        } catch (error) { return { outcome: valid(request) ? 'failed' : 'stale', reason: error.message }; }
    }
    async function executeRequest(context) {
        const request = requests.get(context.target?.requestId);
        if (!request || !valid(request) || context.plan?.planId !== `feedtone-plan-${request.id}`
            || !presetIsComplete(request.prepared)) return { outcome: 'stale', reason: 'Original tone request is no longer current.' };
        if (committing) return { outcome: 'unavailable', reason: 'An earlier audio transaction is still settling.' };
        committing = true;
        let snapshot = null, settings = null, touched = false;
        try {
            const audio = desktop();
            const started = performance.now();
            if (request.reuseBank && request.reuseBank === nativeBank) {
                const bank = nativeBank, selected = bank.entries.find(item => item.key === bankKey(request));
                const chain = await audio.getChainState();
                requireCurrent(request);
                if (chain.length !== bank.entries.length || bank.entries.some((entry, index) => entry.slotId !== chain[index].id)) {
                    nativeBank = null;
                    throw new Error('The preloaded chain changed. Re-enable following to rebuild its tones.');
                }
                const result = await audio.setMultiBypass(bank.entries.map(item => ({ slotId: item.slotId, bypassed: item !== selected })));
                if (result === false) throw new Error('The native tone switch failed.');
                requireCurrent(request);
                active = request.identity;
                playing = { slotId: selected.slotId, postGain: selected.payload.native_preset.chain[0].postGain ?? 1, request };
                listening.gain = null;
                await updateSectionMix();
                try { localStorage.setItem('slopsmith-signal-chain', JSON.stringify(chain.map(slot => ({ ...slot, bypassed: slot.id !== selected.slotId })))); } catch (_) {}
                window.feedBack?.emit?.('feedtone:tone-switched', { tone: request.label, durationMs: performance.now() - started, preloaded: true });
                say(`${request.edited ? 'Playing saved song tone' : 'Playing original tone'}: ${request.label}.`);
                return { outcome: 'handled', payload: { slotsLoaded: bank.entries.length, preloaded: true } };
            }
            settings = hostSettings();
            const inputGate = inputGateForLoad(settings.noiseGate);
            snapshot = await audio.savePreset();
            const previous = typeof snapshot === 'string' ? JSON.parse(snapshot) : snapshot;
            if (!previous || !Array.isArray(previous.chain)) throw new Error('The current chain could not be saved for rollback.');
            if (typeof snapshot !== 'string') snapshot = JSON.stringify(snapshot);
            requireCurrent(request);
            touched = true;
            await audio.setGain('chain', 0);
            requireCurrent(request);
            // Input conditioning belongs to the hardware setup, including during
            // the native load itself so high-gain rigs never open with it disabled.
            const entries = request.bankEntries;
            const preset = { ...request.prepared, noiseGate: inputGate,
                ...(entries ? { chain: entries.map(item => ({ ...item.payload.native_preset.chain[0], bypassed: item.key !== bankKey(request) })) } : {}) };
            const result = await audio.loadPreset(JSON.stringify(preset));
            if (!result || result.success !== true || result.slotsLoaded !== preset.chain.length) throw new Error(result?.error || 'The complete tone chain did not load.');
            requireCurrent(request);
            const chain = await audio.getChainState();
            requireCurrent(request);
            const samePath = (a, b) => String(a).replace(/\\/g, '/').toLowerCase() === String(b).replace(/\\/g, '/').toLowerCase();
            if (!Array.isArray(chain) || chain.length !== preset.chain.length || chain.some((slot, index) => slot.type !== 0
                || !samePath(slot.path, preset.chain[index].path) || slot.bypassed !== preset.chain[index].bypassed)) throw new Error('The audio engine did not confirm the complete tone chain.');
            await applyHostSettings({ outputGain: 1,
                noiseGate: inputGate, tonePolish: { enabled: false } }, () => requireCurrent(request));
            requireCurrent(request);
            // Match the audio-engine host persistence schema after a verified native commit.
            try { localStorage.setItem('slopsmith-signal-chain', JSON.stringify(chain)); } catch (_) {}
            const refreshChain = window._refreshChainPanel;
            if (typeof refreshChain === 'function') await refreshChain();
            active = request.identity;
            nativeBank = entries ? { revision, entries: entries.map((item, index) => ({ ...item, slotId: chain[index].id })) } : null;
            const selectedId = nativeBank?.entries.find(item => item.key === bankKey(request))?.slotId ?? chain[0].id;
            playing = { slotId: selectedId, postGain: request.prepared.chain[0].postGain ?? 1, request };
            listening.gain = null;
            if (request.customDefinition && !request.sectionRig) designer.live = { slotId: chain[0].id, controls: request.controls };
            updateSectionMix().catch(error => listenMessage(error.message));
            inputGateRestored = true;
            try { localStorage.setItem(inputGateKey, JSON.stringify(inputGate)); } catch (_) {}
            say(`${request.customDefinition ? 'Previewing tone' : request.edited ? 'Playing saved song tone' : 'Playing original tone'}: ${request.label}.`);
            return { outcome: 'handled', payload: { slotsLoaded: chain.length } };
        } catch (error) {
            let reason = error.message;
            // Never overwrite a different provider after it takes ownership of the shared route.
            if (touched && snapshot && (!route() || ownsRoute())) {
                try {
                    const audio = desktop();
                    await audio.clearChain();
                    const result = await audio.loadPreset(snapshot);
                    if (result === false || result?.success === false) throw new Error('native rollback failed');
                    await applyHostSettings(settings, () => { if (route() && !ownsRoute()) throw new Error('Another provider now owns the route'); });
                    const chain = await audio.getChainState();
                    try { localStorage.setItem('slopsmith-signal-chain', JSON.stringify(chain)); } catch (_) {}
                } catch (rollback) { reason += ` Rollback failed: ${rollback.message}.`; }
            }
            return { outcome: valid(request) ? 'failed' : 'stale', reason };
        } finally { committing = false; }
    }
    function registerHost() {
        const candidate = window.feedBack?.audioEffects;
        if (!candidate || candidate.version !== 1 || !['registerProvider', 'registerExecutor', 'selectChain', 'loadPlan', 'inspectRoute', 'releaseRoute'].every(name => typeof candidate[name] === 'function')) {
            say('This FeedBack version needs the audio-effects v1 provider/executor APIs. The current audio chain is retained.');
            return false;
        }
        if (host === candidate) return true;
        host = candidate;
        host.registerProvider({ pluginId: 'feedtone', providerId, routeKey, label: 'FeedTone song tones',
            operationHandlers: { 'chain.resolve': resolveRequest } });
        host.registerExecutor({ pluginId: 'feedtone', executorId, routeKey, label: 'FeedTone engine',
            providerIds: [providerId], supportedKinds: ['vst'], maxStages: 1,
            loadChainPlan: executeRequest, releaseRoute: () => ({ outcome: 'handled', reason: 'Tone following stopped; the current audio chain is retained.' }) });
        return true;
    }
    async function follow() {
        if (!following() || designerPreview || !song || loading || !registerHost()) return;
        if (!ownsRoute()) { say('Paused: another audio provider owns the route. Turn following off and on to select FeedTone.'); return; }
        const arr = arrangement();
        if (!arr) { say('Cannot identify the active original arrangement. The current audio chain is retained.'); return; }
        const sectionRig = sectionAt()?.rig_id;
        const key = toneAt(arr), identity = `${filename}|${arr.id}|${sectionRig ? 'rig:' + sectionRig : key}`;
        if (identity === active || identity === requested) return;
        requested = identity;
        const exact = (arr.tone_plans || []).filter((p, index) => sourceKey(p.original_key ?? arr.definitions?.[index]?.Key) === sourceKey(key));
        const candidates = exact.length ? exact.slice(0, 1) : (arr.tone_plans || []).filter(p => p.tone_key === key || p.aliases.includes(key));
        if (!sectionRig && candidates.length !== 1) { say('Original tone reference is missing or ambiguous. The current audio chain is retained.'); return; }
        const tone = candidates[0];
        if (!sectionRig && !tone.plan.renderable) { say('This complete original tone is not supported yet. The current audio chain is retained.'); return; }
        const request = { id: ++sequence, deadline: Date.now() + 60000, revision, filename, arrangementId: arr.id, key, toneKey: tone?.tone_key,
            identity, label: tone?.aliases[0] || key };
        if (sectionRig) {
            const rig = designer.rigs.find(item => item.id === sectionRig);
            if (!rig) { say('The saved section rig is unavailable. The current chain is retained.'); return; }
            Object.assign(request, { sectionRig, customDefinition: copy(rig.definition), sourceContext: { rig_id: rig.id, song_filename:filename }, label: rig.name });
        }
        requests.clear(); requests.set(request.id, request);
        loading = true;
        try {
            const result = await host.loadPlan({ routeKey, providerId, executorId, authorization: 'playback-session',
                target: { requestId: request.id }, timeoutMs: 60000 }, 'feedtone');
                if (valid(request) && result.outcome !== 'handled') say(result.reason || 'The original tone could not be loaded.');
        } catch (error) { if (valid(request)) say(error.message); }
        finally { loading = false; }
    }
    function restoreSelection() {
        if (!enabled || restored || !registerHost()) return;
        restored = true;
        const previous = route();
        if (previous && previous.providerId !== providerId) return;
        const selected = host.selectChain({ routeKey, providerId, authorization: 'restore-selection' }, 'feedtone');
    }
    const copy = value => JSON.parse(JSON.stringify(value));
    const post = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    function editorMessage(message) {
        const node = element('rst-designer-state');
        if (node) node.textContent = displayName(message);
    }
    function setOptions(select, items, selected) {
        select.replaceChildren();
        for (const [value, label] of items) {
            const option = document.createElement('option');
            option.value = value; option.textContent = displayName(label); select.append(option);
        }
        if (selected != null && items.some(item => item[0] === selected)) select.value = selected;
    }
    function editorButtons() {
        for (const id of ['ft-song-picker','rst-arrangement','rst-tone','ft-song-play','ft-song-position']) if (element(id)) element(id).disabled=designer.busy;
        for (const id of ['rst-preview', 'rst-save-rig']) element(id).disabled = designer.busy || !designer.draft;
        element('rst-reset-song').disabled=designer.busy || !designer.context;
        element('rst-save-song').disabled=designer.busy || !(designer.context || designer.file && designer.song?.duration && element('rst-arrangement').value);
        for (const id of ['rst-load-rig', 'rst-delete-rig']) element(id).disabled = designer.busy || !element('rst-library').value;
        element('rst-resume').disabled = designer.busy || !current().filename;
        element('rst-save-rig').textContent=designer.rigId?'Save rig':'Save new rig';
        const origin = designer.context ? `${designer.file} / ${designer.context.arrangement_id}` : 'Personal rig';
        element('rst-origin').textContent = origin + (designer.dirty ? ' / Unsaved changes' : '');
    }
    function markEdited(rebuild = false) {
        designer.dirty = true; designer.version++;
        if (rebuild) { designer.live = null; schedulePreview(); }
        editorButtons();
    }
    function discardDraft() {
        return !designer.dirty || window.confirm('Discard the unsaved tone edits? Saved rigs and source song files will remain available.');
    }
    async function editorAction(action) {
        if (designer.busy) return;
        designer.busy = true; editorButtons();
        try { await action(); }
        catch (error) { editorMessage(error.message); }
        finally { designer.busy = false; editorButtons(); }
    }
    async function loadEditorTone() {
        if (!designer.song || !element('rst-tone').value) return;
        const version = ++designer.version;
        const context = { filename: designer.file, arrangement_id: element('rst-arrangement').value, tone_key: element('rst-tone').value };
        const loaded = await api('designer/tone?' + new URLSearchParams(context));
        if (version !== designer.version) return;
        designer.context = { ...context, tone_key: loaded.tone_key, source_hash: loaded.source_hash };
        designer.draft = copy(loaded.definition); designer.dirty = false; designer.live = null; designer.rigId = null;
        designer.importedVolume = { raw: designer.draft.Volume, value: loaded.interpreted_volume };
        drawDraft();
        if (presentation.autoPreview) schedulePreview();
        editorMessage(loaded.stale_override ? 'The source tone changed. Its old personal override was not applied.'
            : loaded.has_override ? 'Personal song override loaded. Restore original tone to return to the FeedPak settings.' : 'Original song tone loaded.');
    }
    async function loadEditorArrangement(selectedTone) {
        const arrangement = designer.song?.arrangements.find(item => item.id === element('rst-arrangement').value);
        const tones = arrangement?.tone_plans || [];
        setOptions(element('rst-tone'), tones.map(item => [item.tone_key, (item.aliases[0] || item.tone_key) + (item.has_override ? ' / edited' : '')]), typeof selectedTone === 'string' ? selectedTone : undefined);
        if (tones.length) await loadEditorTone();
        else { designer.context = null; newDraft(); }
        drawAuthoredSections(); await syncListening();
    }
    function syncDesignerSong(force = false) {
        if (!designer.bound || !song || !designer.catalog || (!force && (designer.dirty || designer.browsed && !inPlayer()))) return;
        designer.song = song; designer.file = filename;
        const arrangements = song.arrangements;
        const previous = designer.context?.filename === filename ? designer.context : null;
        const selected = previous?.arrangement_id || arrangement()?.id;
        setOptions(element('rst-arrangement'), arrangements.map(item => [item.id, item.name]), selected);
        return loadEditorArrangement(previous?.tone_key).catch(error => editorMessage(error.message));
    }
    function newDraft(keepSong=false) {
        designer.context = keepSong ? designer.context : null; designer.rigId = null; designer.version++; designer.live = null; designer.dirty = true;
        designer.draft = { Name: 'My tone', Key: 'UserTone', Volume: designer.catalog.volume.default, GearList: {}, ChainOrder: designer.catalog.slots.map(slot=>slot.id) };
        drawDraft(); editorMessage('Add equipment to hear your rig live. Drag devices to change their order.');
    }
    async function updateLiveControl(slot, control, value) {
        const live = designer.live;
        if (!designerPreview || !live || !ownsRoute() || loading || committing) { schedulePreview(); return; }
        const parameter = live.controls.find(item => item.slot === slot && item.name === control.name);
        if (!parameter) return;
        const width = parameter.maximum - parameter.minimum;
        if (!width) return;
        try {
            const result = await desktop().setParameter(live.slotId, parameter.id, (value - parameter.minimum) / width);
            if (result === false) throw new Error('The live knob update failed. Updating the live rig…');
        } catch (error) { designer.live = null; editorMessage(error.message); }
    }
    const displayName = value => String(value || '').replace(/rock\s*smith|ubi\s*soft/ig, '').trim();
    const slotName = value => value.replace(/([a-z])([A-Z0-9])/g, '$1 $2');
    function face(device, gear = null, interactive = false) {
        const art = device?.appearance?.image;
        if (!art) { const empty = document.createElement('span'); empty.className = 'ft-empty-glyph'; empty.textContent = device ? displayName(device.name) : '+'; return empty; }
        const img = document.createElement('img'); img.src = art.url; img.alt = displayName(device.name); img.loading = interactive ? 'eager' : 'lazy'; img.draggable = false;
        const frame = document.createElement('span'); frame.className = 'ft-art-frame';
        const body = document.createElement('span'); body.className = 'ft-art';
        body.style.setProperty('--art-ratio', String(art.dimensions[0] / art.dimensions[1])); body.style.setProperty('--face-image', `url("${art.url}")`); body.append(img);
        for (const region of art.badges) {
            const badge = document.createElement('span'); badge.className = 'ft-brand-mask'; badge.setAttribute('aria-hidden', 'true');
            const plate = document.createElement('span'); plate.className = 'ft-art-badge'; plate.textContent = 'FeedTone'; badge.append(plate);
            if (device.type === 'Amps' && region.width > .25 && !region.vertical) badge.classList.add('ft-brand-mask-tolex');
            Object.assign(badge.style, { left: region.x * 100 + '%', top: region.y * 100 + '%', width: region.width * 100 + '%', height: region.height * 100 + '%' });
            if (region.vertical) badge.classList.add('ft-art-badge-vertical');
            body.append(badge);
        }
        for (const visual of device.appearance.knobs || []) {
            const control = device.controls.find(item => item.name === visual.RTPC);
            const [width, height] = art.dimensions;
            if (!control || control.name === '0' || !Number.isFinite(visual.PosX) || !Number.isFinite(visual.PosY)
                || visual.PosX < 0 || visual.PosX > width || visual.PosY < 0 || visual.PosY > height) continue;
            const knob = document.createElement(interactive ? 'button' : 'span');
            const base = visual.Base || '';
            const size = /slider/.test(base) ? 20 : /rackeffect/.test(base) ? 24 : /pedal/.test(base)
                ? /xl/.test(base) ? 80 : /large/.test(base) ? 64 : /small/.test(base) ? 40 : 50
                : /large|lrg/.test(base) ? 52 : /small|sm_/.test(base) ? 30 : 38;
            knob.className = 'ft-face-knob' + (/slider/.test(base) ? ' ft-face-slider' : /switch|button/.test(base) ? ' ft-face-switch' : '');
            knob.dataset.control = control.name;
            Object.assign(knob.style, {left: visual.PosX / width * 100 + '%', top: visual.PosY / height * 100 + '%', width: size / width * 100 + '%'});
            const cap = document.createElement('span'); cap.className = 'ft-knob-cap'; knob.append(cap);
            if (interactive) {
                knob.type = 'button'; knob.setAttribute('role', 'slider'); knob.setAttribute('aria-label', control.label);
                knob.setAttribute('aria-valuemin', control.minimum); knob.setAttribute('aria-valuemax', control.maximum);
                knob.disabled = control.editable === false;
                const readout = document.createElement('span'); readout.className = 'ft-face-readout'; knob.append(readout);
            } else knob.setAttribute('aria-hidden', 'true');
            setFaceValue(knob, control, gear?.KnobValues?.[control.name] ?? control.default);
            body.append(knob);
        }
        frame.append(body); return frame;
    }
    function setFaceValue(knob, control, value) {
        const fraction = Math.max(0, Math.min(1, (value - control.minimum) / (control.maximum - control.minimum || 1)));
        knob.style.setProperty('--dial-angle', `${-135 + fraction * 270}deg`);
        const text = control.choices?.find(choice => Number(choice.value) === Number(value))?.label ?? String(Number(Number(value).toFixed(2)));
        knob.setAttribute('aria-valuemin', Math.min(control.minimum, value)); knob.setAttribute('aria-valuemax', Math.max(control.maximum, value));
        knob.setAttribute('aria-valuenow', value); knob.setAttribute('aria-valuetext', text);
        knob.title = `${control.label}: ${text}`;
        const readout = knob.querySelector('.ft-face-readout'); if (readout) readout.textContent = text;
    }
    function bindFaceControl(knob, control, input, change) {
        const step = control.step > 0 ? control.step : (control.maximum - control.minimum) / 100;
        const choices = control.choices?.map(choice => Number(choice.value));
        const clamp = value => Math.max(control.minimum, Math.min(control.maximum, value));
        const apply = value => {
            if (choices?.length) value = choices.reduce((nearest, item) => Math.abs(item-value) < Math.abs(nearest-value) ? item : nearest);
            change(clamp(value));
        };
        knob.addEventListener('keydown', event => {
            let value = Number(input.value);
            if (event.key === 'Home') value = control.minimum;
            else if (event.key === 'End') value = control.maximum;
            else if (['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft'].includes(event.key)) {
                const direction = ['ArrowUp','ArrowRight'].includes(event.key) ? 1 : -1;
                value = choices?.length ? choices[Math.max(0, Math.min(choices.length-1, choices.indexOf(value)+direction))]
                    : value + step * direction * (event.shiftKey ? .1 : 1);
            } else return;
            event.preventDefault(); apply(value);
        });
        let drag = null;
        knob.addEventListener('pointerdown', event => {
            if (event.button !== 0 || knob.disabled) return;
            event.preventDefault(); knob.focus(); knob.setPointerCapture(event.pointerId);
            drag = { y: event.clientY, value: Number(input.value) }; knob.classList.add('is-adjusting');
        });
        knob.addEventListener('pointermove', event => {
            if (!drag) return;
            apply(drag.value + (drag.y-event.clientY) / (event.shiftKey ? 1500 : 150) * (control.maximum-control.minimum));
        });
        const finish = () => { drag = null; knob.classList.remove('is-adjusting'); };
        knob.addEventListener('pointerup', finish); knob.addEventListener('pointercancel', finish); knob.addEventListener('lostpointercapture', finish);
        knob.addEventListener('dblclick', () => apply(control.default));
    }
    function drawEquipment() {
        if (!designer.catalog || !designer.draft) return;
        const filter = presentation.gearFilter || 'All', query = element('ft-equipment-search').value.trim().toLowerCase();
        const list = element('ft-equipment-list'); list.replaceChildren();
        let devices = designer.catalog.devices.filter(device => (filter === 'All' || device.type === filter)
            && (!query || `${device.name} ${device.category} ${device.key}`.toLowerCase().includes(query)));
        const selected = designer.draft.GearList[designer.selectedSlot]?.Key;
        // Keep the active model visible without changing the catalog's stable order.
        devices = [...devices.filter(device => device.key === selected), ...devices.filter(device => device.key !== selected)];
        for (const device of devices) {
            const button = document.createElement('button'); button.type = 'button'; button.className = 'ft-equipment-item';
            button.dataset.deviceKey = device.key; button.setAttribute('aria-pressed', String(device.key === selected));
            button.append(face(device)); const name = document.createElement('span'); name.textContent = displayName(device.name); button.append(name);
            button.addEventListener('click', () => {
                let target = designer.selectedSlot;
                if (!designer.draft.ChainOrder && !device.slots.includes(target)) target = device.slots.find(slot => !designer.draft.GearList[slot]) || device.slots[0];
                designer.selectedSlot = target; chooseDevice(device.key);
            }); list.append(button);
        }
        if (!devices.length) { const empty = document.createElement('p'); empty.className = 'ft-help'; empty.textContent = 'No matching equipment.'; list.append(empty); }
        element('ft-equipment-target').textContent = `Add or replace in ${slotName(designer.selectedSlot)} · ${devices.length} models`;
    }
    function chooseDevice(key) {
        const slot = designer.selectedSlot;
        if (!key) delete designer.draft.GearList[slot];
        else { const device = designer.catalog.devices.find(item => item.key === key);
            if (!device.slots.includes(slot)) designer.draft.ChainOrder ||= designer.catalog.slots.map(item=>item.id);
            const knobs = Object.fromEntries(device.controls.filter(control => control.name !== '0' && Number.isFinite(control.default)).map(control => [control.name,control.default]));
            designer.draft.GearList[slot] = {Key:device.key,PedalKey:device.key,Type:device.type,KnobValues:knobs}; }
        markEdited(true); drawSlots(); editorMessage('Device changed. Updating live guitar…');
    }
    function orderedSlots() {
        return (designer.draft?.ChainOrder || designer.catalog.slots.map(slot=>slot.id)).map(id=>designer.catalog.slots.find(slot=>slot.id===id));
    }
    function moveDevice(target, reorder=false, after=false) {
        const source = designer.selectedSlot;
        if (source === target || !designer.draft.GearList[source] || !designer.catalog.slots.some(slot=>slot.id===target)) return;
        if (!reorder) {
            const gear=designer.draft.GearList,temporary=gear[target];gear[target]=gear[source];if(temporary)gear[source]=temporary;else delete gear[source];
            const fits=Object.entries(gear).every(([id,value])=>designer.catalog.devices.find(device=>device.key===value.Key)?.slots.includes(id));
            if(!fits)designer.draft.ChainOrder ||= orderedSlots().map(slot=>slot.id);
            designer.selectedSlot=target;markEdited(true);drawSlots();return;
        }
        const order = orderedSlots().map(slot=>slot.id).filter(id=>id!==source);
        order.splice(order.indexOf(target)+(after?1:0),0,source); designer.draft.ChainOrder = order;
        markEdited(true); drawSlots(); editorMessage('Signal chain updated.');
    }
    function drawBrowser() {
        if (!designer.catalog || !designer.draft) return;
        const query=element('rst-gear-search').value.trim().toLowerCase(), list=element('rst-device-list'); list.replaceChildren();
        const devices=designer.catalog.devices.filter(d=>(designer.draft.ChainOrder || d.slots.includes(designer.selectedSlot)) && (!query || `${d.name} ${d.key} ${d.category}`.toLowerCase().includes(query)));
        for (const device of devices) { const button=document.createElement('button'); button.type='button';button.className='ft-catalog-item';button.dataset.deviceKey=device.key;button.append(face(device));const name=document.createElement('strong');name.textContent=displayName(device.name);button.append(name);const sub=document.createElement('small');sub.textContent=device.type==='Cabinets'?device.key.replace(/^Cab_/,'').replace(/_/g,' / '):displayName(device.category);button.append(sub);button.addEventListener('click',()=>{chooseDevice(device.key);element('rst-device-browser').hidden=true;});list.append(button); }
        if (!devices.length) {const note=document.createElement('p');note.className='ft-help';note.textContent='No matching devices for this position.';list.append(note);}
    }
    function drawSlots() {
        if (!designer.catalog || !designer.draft) return;
        designer.draft.GearList ||= {};
        if (!designer.selectedSlot) designer.selectedSlot=designer.draft.GearList.Amp?'Amp':designer.catalog.slots.find(s=>designer.draft.GearList[s.id])?.id || designer.catalog.slots[0].id;
        const parent=element('rst-slots');parent.replaceChildren();
        parent.dataset.showEmpty = String(!!presentation.showEmpty || !Object.values(designer.draft.GearList).some(Boolean));
        for (const slot of orderedSlots()) {
            const gear=designer.draft.GearList[slot.id], device=designer.catalog.devices.find(d=>d.key===gear?.Key);
            const tile=document.createElement('button');tile.type='button';tile.className='rst-slot' + (gear ? '' : ' is-empty');tile.dataset.slot=slot.id;tile.setAttribute('aria-pressed',String(slot.id===designer.selectedSlot));tile.setAttribute('aria-label',`${slotName(slot.id)}: ${displayName(device?.name || gear?.Key || 'Empty')}`);
            const caption=document.createElement('small');caption.textContent=gear ? (device?.type || 'DEVICE').toUpperCase() : slot.id.replace('PrePedal','Pre ').replace('PostPedal','Post ').replace('Rack','Rack ');tile.append(caption,face(device, gear));const name=document.createElement('strong');name.textContent=displayName(device?.name || gear?.Key || 'Add device');tile.append(name);
            tile.addEventListener('click',()=>{designer.selectedSlot=slot.id;drawSlots();});tile.draggable=!!gear;tile.addEventListener('dragstart',event=>{event.dataTransfer.setData('text/plain',slot.id);event.dataTransfer.effectAllowed='move';tile.classList.add('ft-chain-dragging');});tile.addEventListener('dragend',()=>tile.classList.remove('ft-chain-dragging'));tile.addEventListener('keydown',event=>{if(!event.altKey || !['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();event.stopPropagation();const order=orderedSlots().map(s=>s.id),index=order.indexOf(slot.id),target=order[index+(event.key==='ArrowLeft'?-1:1)];if(target){designer.selectedSlot=slot.id;moveDevice(target,true,event.key==='ArrowRight');}});tile.addEventListener('dragover',event=>event.preventDefault());tile.addEventListener('drop',event=>{event.preventDefault();const source=event.dataTransfer.getData('text/plain');if(designer.catalog.slots.some(s=>s.id===source)){designer.selectedSlot=source;moveDevice(slot.id,true,event.clientX>tile.getBoundingClientRect().left+tile.getBoundingClientRect().width*.65);}});parent.append(tile);
        }
        const slot=designer.catalog.slots.find(item=>item.id===designer.selectedSlot), gear=designer.draft.GearList[slot.id], device=designer.catalog.devices.find(item=>item.key===gear?.Key);
        element('rst-selected-slot').textContent=slotName(slot.id); element('rst-device-image').replaceChildren(face(device, gear, true));
        element('ft-device-name').textContent = displayName(device?.name || 'Choose a device');
        element('ft-device-category').textContent = device ? ({Amps:'AMPLIFIER',Cabinets:'CABINET',Pedals:'PEDAL',Racks:'RACK EFFECT'}[device.type] || device.category) : slotName(slot.id);
        element('rst-device-image').dataset.kind = device?.type || 'empty';
        const selector=element('rst-device');setOptions(selector,[['','Empty'],...designer.catalog.devices.filter(d=>designer.draft.ChainOrder || d.slots.includes(slot.id)).map(d=>[d.key,displayName(d.name)+(d.type==='Cabinets'?'  /  '+d.key.replace(/^Cab_/,'').replace(/_/g,' / '):'')])],gear?.Key || '');
        element('rst-remove-device').disabled=!gear;
        setOptions(element('rst-move-target'),[['','Choose destination'],...designer.catalog.slots.filter(s=>s.id!==slot.id).map(s=>[s.id,slotName(s.id)])]);
        element('rst-move-device').disabled=!gear;
        const card=element('rst-controls');card.replaceChildren();
        if (gear && !device) {const note=document.createElement('p');note.className='ft-help';note.textContent='Unknown source device. Choose a supported device to preview.';card.append(note);}
        if (!gear) {const note=document.createElement('p');note.className='ft-help';note.textContent='This position is empty. Browse the collection to add a device.';card.append(note);}
        for (const control of device?.controls || []) {
                if (control.name === '0') continue;
                const row = document.createElement('div'); row.className = 'rst-knob';
                const dial = document.createElement('div'); dial.className = 'ft-dial'; dial.setAttribute('aria-hidden','true'); row.append(dial);
                const label = document.createElement('label'); label.textContent = control.label + (control.unit && control.unit !== 'number' ? ` (${control.unit})` : '');
                const inputId = `rst-${slot.id}-${control.name}`; label.htmlFor = inputId; row.append(label);
                const value = gear.KnobValues?.[control.name] ?? control.default;
                dial.style.setProperty('--dial-angle', `${-135 + 270 * Math.max(0,Math.min(1,(value-control.minimum)/(control.maximum-control.minimum || 1)))}deg`);
                const input = document.createElement(control.choices?.length ? 'select' : 'input'); input.id = inputId;
                if (control.choices?.length) {
                    const choices = control.choices.map(choice => [String(choice.value), String(choice.label)]);
                    if (!control.choices.some(choice => Number(choice.value) === Number(value))) choices.unshift([String(value), `Authored value: ${value}`]);
                    setOptions(input, choices, String(value));
                }
                else { input.type = 'number'; input.min = Math.min(control.minimum, value); input.max = Math.max(control.maximum, value); input.step = control.step > 0 ? control.step : 'any'; input.value = value; }
                input.disabled = control.editable === false; row.append(input);
                const faceKnob = [...element('rst-device-image').querySelectorAll('[data-control]')].find(knob => knob.dataset.control === control.name);
                let slider = null;
                if (!control.choices?.length && control.maximum > control.minimum && control.editable !== false) {
                    slider = document.createElement('input'); slider.type = 'range'; slider.min = control.minimum; slider.max = control.maximum; slider.step = 'any'; slider.value = value;
                    slider.setAttribute('aria-label', `${slot.id}: ${control.label}`); row.append(slider);
                }
                const change = number => {
                    if (!Number.isFinite(number) || number < control.minimum || number > control.maximum) { editorMessage(`${control.label} must be between ${control.minimum} and ${control.maximum}.`); return; }
                    if (control.choices?.length && !control.choices.some(choice => Number(choice.value) === number)) return;
                    gear.KnobValues ||= {}; gear.KnobValues[control.name] = number;
                    input.value = String(number); if (slider) slider.value = String(number);
                    dial.style.setProperty('--dial-angle', `${-135 + 270 * (number-control.minimum)/(control.maximum-control.minimum || 1)}deg`);
                    if (faceKnob) setFaceValue(faceKnob, control, number);
                    markEdited(); updateLiveControl(slot.id, control, number);
                };
                input.addEventListener(control.choices?.length ? 'change' : 'input', () => { if (input.value !== '') change(Number(input.value)); });
                if (slider) slider.addEventListener('input', () => change(Number(slider.value)));
                if (faceKnob && control.editable !== false) bindFaceControl(faceKnob, control, input, change);
                if (control.behavior !== 'active') {
                    const note = document.createElement('p'); note.className = 'rst-help'; note.style.gridColumn = '1/-1';
                    note.textContent = control.behavior === 'authored-inert' ? 'This control has no audio effect in the source device.' : 'Original metadata control; no audio parameter.'; row.append(note);
                }
                card.append(row);
            }
        const count = card.children.length || 1;
        card.style.setProperty('--ft-knob-columns', String(Math.ceil(count / Math.ceil(count / 6))));
        drawBrowser(); drawEquipment();
    }
    function drawDraft() {
        if (!designer.draft || !designer.catalog) return;
        if (!designer.draft.GearList?.[designer.selectedSlot]) {
            designer.selectedSlot = designer.draft.GearList?.Amp ? 'Amp'
                : designer.catalog.slots.find(slot => designer.draft.GearList?.[slot.id])?.id || designer.selectedSlot;
        }
        element('rst-name').value = displayName(designer.draft.Name || designer.draft.Key || '');
        const volume = element('rst-volume'), source = designer.catalog.volume;
        const raw = designer.draft.Volume ?? 0;
        const interpreted = !Number.isFinite(Number(raw)) && designer.importedVolume?.raw === raw
            && typeof designer.importedVolume.value === 'number' && Number.isFinite(designer.importedVolume.value);
        const value = interpreted ? designer.importedVolume.value : Number(raw), finite = Number.isFinite(value);
        volume.min = finite ? Math.min(source.minimum, value) : source.minimum;
        volume.max = finite ? Math.max(source.maximum, value) : source.maximum;
        volume.value = finite ? value : '';
        syncToneFader();
        element('rst-volume-help').textContent = interpreted
            ? `Imported level plays at ${value} dB. Its original text (${String(raw).slice(0,120)}) is preserved until you edit the level.`
            : finite
            ? 'Rig gain. Use the Mix tab for listening levels; 0 dB selects the authored fallback.'
            : `The source Volume (${String(designer.draft.Volume).slice(0,120)}) is invalid. Enter a finite dB value before previewing this tone.`;
        drawSlots(); editorButtons();
    }
    async function refreshRigs(selected) {
        const result = await api('designer/rigs'); designer.rigs = result.rigs;
        setOptions(element('rst-library'), [['', 'Choose a saved rig'], ...designer.rigs.map(rig => [rig.id, rig.name])], selected);
        editorButtons();
        if (listening.bound) updateSectionChoices();
    }
    async function previewDraft() {
        if (!registerHost() || !compatibleHost()) throw new Error('The desktop audio engine is not ready.');
        const selected = host.selectChain({ routeKey, providerId, authorization: 'user-action' }, 'feedtone');
        if (selected.outcome !== 'handled') throw new Error(selected.reason);
         restored = true; designerPreview = true; designer.live = null; invalidate();
        const request = { id: ++sequence, deadline: Date.now() + 60000, revision,
            identity: `designer:${designer.version}`, label: designer.draft.Name || 'My tone',
            customDefinition: copy(designer.draft), sourceContext: { ...(designer.context || (designer.file ? {song_filename:designer.file}:{})), ...(designer.rigId ? { rig_id: designer.rigId } : {}) }, draftRevision: designer.version };
        requests.set(request.id, request); loading = true;
        try {
            const result = await host.loadPlan({ routeKey, providerId, executorId, authorization: 'user-action', target: { requestId: request.id }, timeoutMs: 60000 }, 'feedtone');
            if (result.outcome !== 'handled') throw new Error(result.reason || 'Tone preview failed.');
            editorMessage('Live guitar active. Changes are heard automatically.');
        } finally { loading = false; }
    }
    async function refreshFollowingOverride() {
        if (current().filename !== designer.context?.filename) return;
        filename = ''; invalidate(); await refresh();
    }
    function schedulePreview() {
        clearTimeout(previewTimer);
        if (!presentation.autoPreview || !designer.draft) return;
        previewTimer=setTimeout(()=>{
            if (designer.busy || loading || committing) { schedulePreview(); return; }
            editorAction(previewDraft);
        },180);
    }
    async function hostJson(url) {
        const response=await fetch(url), result=await response.json();
        if (!response.ok) throw new Error(result.detail || result.error || 'Song library is unavailable');
        return result;
    }
    const library={page:0,token:0,items:[],total:0};
    async function searchSongs() {
        const token=++library.token, q=element('ft-song-search').value;
        try {
            const result=await hostJson('/api/library?'+new URLSearchParams({q,page:library.page,size:30,format:'sloppak'}));
            if (token!==library.token) return;
            library.items=result.songs || []; library.total=result.total || 0;
            setOptions(element('ft-song-picker'),[['','Choose a song…'],...library.items.map(item=>[item.filename,`${item.artist} — ${item.title}`])],designer.file);
            element('ft-song-results').textContent=`${library.page*30+1}–${library.page*30+library.items.length} / ${library.total}`;
            element('ft-song-prev').disabled=library.page===0; element('ft-song-next').disabled=(library.page+1)*30>=library.total;
        } catch(error) { if(token===library.token) element('ft-song-results').textContent=error.message; }
    }
    async function chooseSong(file) {
        if (!file || !discardDraft()) return;
        await stopSongPreview();
        const loaded=await api('song?filename='+encodeURIComponent(file));
        designer.song=loaded; designer.file=file; designer.browsed=true; designer.context=null;
        presentation.autoPreview=true;
        element('ft-selected-song').textContent=displayName(`${loaded.artist} — ${loaded.title}`);
        element('ft-song-position').max=loaded.duration || 1;
        const arrangements=loaded.arrangements;
        setOptions(element('rst-arrangement'),arrangements.map(item=>[item.id,item.name]));
        await loadEditorArrangement();
    }
    function authoredSections() {
        const arr=listeningArrangement(); if (!arr) return [];
        const duration=(inPlayer()?song:designer.song)?.duration || 0;
        const markers=arr.sections || [], points=new Set([0,...markers.map(item=>item.start),...arr.changes.map(item=>Number(item.t))]);
        if (duration) points.add(duration);
        const sorted=[...points].filter(value=>Number.isFinite(value) && value>=0 && (!duration || value<=duration)).sort((a,b)=>a-b);
        return sorted.slice(0,-1).map((start,index)=>{
            const marker=markers.filter(item=>item.start<=start).at(-1);
            let tone=arr.base;
            for(const change of [...arr.changes].sort((a,b)=>Number(a.t)-Number(b.t))) if(Number(change.t)<=start) tone=change.name || change.rig;
            const plan=arr.tone_plans.find(item=>sourceKey(item.original_key)===sourceKey(tone)) || arr.tone_plans.find(item=>item.tone_key===tone || item.aliases.includes(tone));
            return {id:'source-'+index,start,end:sorted[index+1],label:marker?`${marker.label}${marker.number?' '+marker.number:''}`:'Intro',tone_key:plan?.tone_key,tone_label:plan?.aliases[0] || tone || 'No tone'};
        });
    }
    function drawAuthoredSections() {
        const list=element('ft-authored-sections'); if (!list) return;
        list.replaceChildren();
        for(const item of authoredSections()) {
            const row=document.createElement('div'); row.className='ft-source-section';
            const label=document.createElement('span'); label.textContent=`${formatTime(item.start)} · ${displayName(item.label)} — ${displayName(item.tone_label)}`;
            const hear=document.createElement('button');hear.type='button';hear.textContent='▶ Hear';
            hear.onclick=()=>editorAction(async()=>{
                if(inPlayer()) { await window.feedBack?.playback?.seek?.(item.start); return; }
                if (!discardDraft()) return;
                presentation.autoPreview=false;
                if(item.tone_key) { element('rst-tone').value=item.tone_key; await loadEditorTone(); }
                await startSongPreview(item.start);
                presentation.autoPreview=true;
            });
            const edit=document.createElement('button');edit.type='button';edit.textContent='Edit';
            edit.onclick=()=>{
                document.querySelector('.ft-custom-sections').open=true;
                element('ft-section-save').dataset.id=item.id;
                for(const field of ['label','start','end']) element('ft-section-'+field).value=item[field];
                element('ft-section-tone').value=item.tone_key || '';
                element('ft-section-guitar').value='';element('ft-section-song').value='';
                element('ft-section-label').focus();
            };
            row.append(label,hear,edit);list.append(row);
        }
        if(!list.children.length) list.textContent=designer.song?'No timed sections in this arrangement. Select a tone above or create a personal range.':'Choose a song to see its sections and tone changes.';
    }
    function formatTime(time) { return `${Math.floor(time/60)}:${String(Math.floor(time%60)).padStart(2,'0')}`; }
    async function localAudio(url) {
        if(typeof url!=='string' || !url.startsWith('/') || url.startsWith('//')) throw new Error('Invalid song audio URL');
        return (await hostJson('/api/audio-local-path?url='+encodeURIComponent(url))).path;
    }
    function previewTransport(action) {
        const next=(preview.transport || Promise.resolve()).catch(()=>{}).then(action);
        preview.transport=next;
        return next;
    }
    async function previewUsesNative() {
        if(typeof desktop()?.loadBackingTrack!=='function') return false;
        const device=await desktop().getCurrentDevice?.();
        if(!device || /asio|exclusive/i.test(device.outputType || device.type || '')) return true;
        preview.audio ||= new Audio();
        const output=device.output || 'Default';
        if(/^default$/i.test(output)) {
            if(preview.audio.setSinkId) await preview.audio.setSinkId('default');
            return false;
        }
        if(preview.audio.setSinkId && navigator.mediaDevices?.enumerateDevices) {
            const devices=await navigator.mediaDevices.enumerateDevices();
            const match=devices.find(item=>item.kind==='audiooutput' && item.label===output);
            if(match) {await preview.audio.setSinkId(match.deviceId);return false;}
        }
        // A native route preserves a specifically selected output when browser routing is unavailable.
        return true;
    }
    async function startSongPreview(position=preview.position) {
        if (!designer.song || inPlayer()) throw new Error('Choose a song in the main Tone Designer first.');
        if(!Number.isFinite(position) || position<0) throw new Error('Invalid preview position');
        const generation=++preview.generation, file=designer.file;
        const current=()=>generation===preview.generation && !inPlayer() && designer.file===file;
        if(!registerHost()) throw new Error('FeedBack audio is unavailable');
        const selected=host.selectChain({routeKey,providerId,authorization:'user-action'},'feedtone');
        if(selected.outcome!=='handled') throw new Error(selected.reason);
        if (window.feedBack?.isPlaying && !preview.active) throw new Error('Pause the current song before starting a library preview.');
        preview.active=true; preview.playing=false; preview.position=position;
        element('ft-song-stop').disabled=false;
        designerPreview=false; designer.live=null; song=designer.song; filename=file; invalidate();
        try {
            await syncListening();
            if(!current()) return;
            await follow();
            if(!current()) return;
            await previewTransport(async()=>{
                if(!current()) return;
                if(preview.loaded!==file) {
                    const metadata=await hostJson('/api/song/'+encodeURIComponent(file)+'?stems=1');
                    if(!current()) return;
                    const url=metadata.full_mix_url || metadata.stems?.find(item=>item.default)?.url;
                    if(!url || typeof url!=='string' || !url.startsWith('/') || url.startsWith('//')) throw new Error('This song has no playable backing audio. Guitar tone preview is still available.');
                    const native=await previewUsesNative();
                    if(!current()) return;
                    if(native) {
                        const path=await localAudio(url);
                        if(!current()) return;
                        if(!preview.loaded) preview.previous={url:window._juceMode?window._juceAudioUrl:null,position:window.jucePlayer?.currentTime || 0};
                        await desktop().stopBacking();
                        if(!current()) return;
                        if(await desktop().loadBackingTrack(path)===false) throw new Error('FeedBack could not load the song preview');
                        preview.native=true;
                    } else {
                        preview.audio.pause();preview.audio.src=url;preview.native=false;
                    }
                    if(!current()) return;
                    preview.loaded=file;
                }
                if(!current()) return;
                const volume=(listening.baseVolume ?? window.feedBack?.audio?.readSongVolume?.() ?? 80)/100;
                if(preview.native) {
                    await desktop().seekBacking(position);
                    if(!current()) return;
                    await desktop().setGain('backing',volume);
                    if(!current()) return;
                    if(await desktop().startBacking()===false) throw new Error('FeedBack could not start the song preview');
                } else {
                    preview.audio.currentTime=position;preview.audio.volume=volume;await preview.audio.play();
                }
                if(!current()) {
                    if(preview.native && !inPlayer()) await desktop().stopBacking();
                    else preview.audio?.pause();
                    return;
                }
                preview.playing=true;
                element('ft-song-play').textContent='Ⅱ Pause';editorMessage('Song preview playing. Your guitar follows this arrangement’s tones.');
            });
        } catch(error) {
            if(current()) {await stopSongPreview();throw error;}
        }
    }
    async function pauseSongPreview() {
        ++preview.generation;preview.playing=false;
        await previewTransport(async()=>{
            if(preview.native && !inPlayer()) await desktop()?.stopBacking?.();else preview.audio?.pause();
        });
        element('ft-song-play').textContent='▶ Continue';
    }
    async function stopSongPreview(restore=true) {
        const generation=++preview.generation, loaded=preview.loaded;
        preview.active=false;preview.playing=false;preview.loaded='';
        await previewTransport(async()=>{
            preview.audio?.pause();
            if(generation!==preview.generation || inPlayer()) return;
            if(preview.native) {
                await desktop()?.stopBacking?.();
                if(restore && preview.previous?.url && generation===preview.generation) {
                    const path=await localAudio(preview.previous.url);
                    if(generation!==preview.generation || inPlayer()) return;
                    await desktop().loadBackingTrack(path);
                    if(generation!==preview.generation || inPlayer()) return;
                    await desktop().seekBacking(preview.previous.position);
                }
            }
        });
        if(generation!==preview.generation) return;
        preview.position=0;preview.previous=null;preview.native=false;
        element('ft-song-play').textContent='▶ Preview song';element('ft-song-stop').disabled=true;
        if(loaded) {invalidate();filename='';song=null;refresh();}
    }
    async function pollPreview() {
        if(preview.polling || !preview.active || !preview.playing || inPlayer()) return;
        preview.polling=true;
        try {
            preview.position=preview.native?await desktop().getBackingPosition():preview.audio.currentTime;
            element('ft-song-position').value=preview.position; element('ft-song-time').textContent=formatTime(preview.position);
            if(designer.song?.duration && preview.position>=designer.song.duration-.1) await pauseSongPreview();
        } catch(error) {editorMessage(error.message);await pauseSongPreview();}
        finally {preview.polling=false;}
    }
    function bindWorkspace() {
        if(presentation.workspaceBound) return; presentation.workspaceBound=true;
        let searchTimer;
        element('ft-song-search').addEventListener('input',()=>{clearTimeout(searchTimer);library.page=0;searchTimer=setTimeout(searchSongs,200);});
        element('ft-song-picker').addEventListener('change',()=>editorAction(()=>chooseSong(element('ft-song-picker').value)));
        for(const [id,direction] of [['ft-song-prev',-1],['ft-song-next',1]]) element(id).addEventListener('click',()=>{library.page+=direction;searchSongs();});
        element('ft-song-play').addEventListener('click',()=>editorAction(()=>preview.playing?pauseSongPreview():startSongPreview()));
        element('ft-song-stop').addEventListener('click',()=>stopSongPreview().catch(error=>editorMessage(error.message)));
        element('ft-song-position').addEventListener('change',()=>editorAction(async()=>{const position=Number(element('ft-song-position').value);if(preview.active){preview.position=position;if(preview.native)await desktop().seekBacking(position);else preview.audio.currentTime=position;follow();}else await startSongPreview(position);}));
        window.feedBack?.on?.('song:loading',()=>stopSongPreview(false).catch(error=>editorMessage(error.message)));
        window.feedBack?.on?.('screen:changed',()=>{if(preview.playing)pauseSongPreview().catch(error=>editorMessage(error.message));syncListening().catch(error=>listenMessage(error.message));});
        searchSongs();setInterval(pollPreview,100);
    }

    function bindDesigner() {
        if (designer.bound || !element('rst-designer')) return;
        designer.bound = true;
        const on = (id, event, handler) => element(id).addEventListener(event, handler);
        on('rst-new', 'click', () => { if (designer.catalog && discardDraft()) { presentation.autoPreview=true; newDraft(true); } });
        on('rst-load-song', 'click', () => { if (discardDraft()) { if (song) syncDesignerSong(true); else editorMessage('Open a converted FeedPak in FeedBack first.'); } });
        on('rst-arrangement', 'change', () => {
            if (!discardDraft()) { if (designer.context) element('rst-arrangement').value = designer.context.arrangement_id; return; }
            presentation.autoPreview=true; editorAction(loadEditorArrangement);
        });
        on('rst-tone', 'change', () => {
            if (!discardDraft()) { if (designer.context) element('rst-tone').value = designer.context.tone_key; return; }
            presentation.autoPreview=true; editorAction(loadEditorTone);
        });
        on('rst-name', 'input', () => { if (designer.draft) { designer.draft.Name = element('rst-name').value; markEdited(); } });
        on('rst-volume', 'input', () => {
            const value = Number(element('rst-volume').value);
            if (!designer.draft || element('rst-volume').value === '' || !Number.isFinite(value)) return;
            designer.draft.Volume = value; markEdited();
            element('rst-volume-help').textContent = value === 0 ? 'Zero selects the authored −36 dB fallback.' : 'Edited tone level. Listening trims are applied separately.';
            const control = designer.live?.controls.find(item => item.slot === 'Tone' && item.name === 'ToneVolume');
            if (control && value >= control.minimum && value <= control.maximum) updateLiveControl('Tone', control, value);
            else { designer.live = null; schedulePreview(); }
        });
        on('rst-gear-search', 'input', drawBrowser);
        on('rst-device','change',()=>chooseDevice(element('rst-device').value));
        on('rst-browse','click',()=>{element('rst-device-browser').hidden=false;drawBrowser();element('rst-gear-search').focus();});
        on('rst-close-browser','click',()=>{element('rst-device-browser').hidden=true;});
        on('rst-remove-device','click',()=>chooseDevice(''));
        on('rst-move-device','click',()=>moveDevice(element('rst-move-target').value));
        on('rst-preview', 'click', () => {presentation.autoPreview=true;editorAction(previewDraft);});
        on('rst-resume', 'click', () => {
            const toggle = element('feedtone-enabled'); toggle.checked = true; toggle.dispatchEvent(new Event('change', { bubbles: true }));
            editorMessage('Following the song timeline again. Your draft stays in the editor.');
        });
        on('rst-save-song', 'click', () => editorAction(async () => {
            if (designer.context) {
                await api('designer/override', post({ ...designer.context, definition: designer.draft })); designer.dirty = false;
                editorMessage('Tone saved for this song.'); await refreshFollowingOverride();
            } else {
                const rig=await api('designer/rigs',post({name:designer.draft.Name || 'My tone',definition:designer.draft,...(designer.rigId?{id:designer.rigId,rig_id:designer.rigId}:{})}));
                designer.rigId=rig.id; await refreshRigs(rig.id);
                const context={filename:designer.file,arrangement_id:element('rst-arrangement').value};
                const stored=await api('sections?'+new URLSearchParams(context));
                const ranges=[{id:'arrangement-rig',label:rig.name,start:0,end:designer.song.duration,rig_id:rig.id},...stored.ranges.filter(item=>item.id!=='arrangement-rig')];
                const saved=await api('sections',post({...context,ranges}));
                listening.ranges=saved.ranges;designer.dirty=false;drawSections();
                editorMessage('Personal rig saved for this song arrangement.');
                if(preview.active){invalidate();designerPreview=false;follow();}
            }
            if (designerPreview) await previewDraft();
        }));
        on('rst-reset-song', 'click', () => editorAction(async () => {
            if (!window.confirm('Restore this song tone to its original FeedPak settings? This removes its personal override.')) return;
            await api('designer/reset', post(designer.context)); await loadEditorTone(); await refreshFollowingOverride();
            if (designerPreview) await previewDraft();
        }));
        on('rst-save-rig', 'click', () => editorAction(async () => {
            const rig = await api('designer/rigs', post({ ...designer.context, ...(designer.rigId ? {id:designer.rigId,rig_id:designer.rigId}:{}), name: designer.draft.Name || 'My tone', definition: designer.draft }));
            designer.dirty = false; await refreshRigs(rig.id); editorMessage('Personal rig saved.');
        }));
        on('rst-library', 'change', editorButtons);
        on('rst-load-rig', 'click', () => {
            if (!discardDraft()) return;
            const rig = designer.rigs.find(item => item.id === element('rst-library').value); if (!rig) return;
            designer.draft = copy(rig.definition); designer.rigId = rig.id; designer.dirty = true; designer.live = null; designer.version++;
            designer.importedVolume = { raw: designer.draft.Volume, value: rig.interpreted_volume };
            drawDraft(); presentation.autoPreview=true; schedulePreview(); editorMessage('Saved rig loaded. Save to song to use it for the selected song tone.');
        });
        on('rst-delete-rig', 'click', () => editorAction(async () => {
            if (!window.confirm('Delete this saved personal rig? Your song files and song overrides stay unchanged.')) return;
            await api('designer/rigs/' + encodeURIComponent(element('rst-library').value), { method: 'DELETE' }); await refreshRigs(); editorMessage('Personal rig deleted.');
        }));
        editorButtons();
        api('designer/catalog').then(value => {
            designer.catalog = value;
            if (song) syncDesignerSong(); else { newDraft(); designer.dirty = false; editorButtons(); }
            return refreshRigs();
        }).catch(error => editorMessage(error.message));
    }
    function listeningArrangement() { return inPlayer() ? arrangement() : designer.song?.arrangements.find(item=>item.id===element('rst-arrangement').value); }
    function listeningFile() { return inPlayer() ? filename : designer.file; }
    function listeningScope() { return listeningFile() && listeningArrangement() ? JSON.stringify([listeningFile(),listeningArrangement().id]) : ''; }
    function listeningContext() {
        const arr=listeningArrangement(), key=element('ft-listen-tone')?.value;
        return listeningFile() ? {filename:listeningFile(), ...(arr ? {arrangement_id:arr.id,...(key ? {tone_key:key}:{})}:{})} : {};
    }
    function listenMessage(message) { const node = element('ft-listen-status'); if (node && node.textContent !== message) node.textContent = displayName(message); }
    async function loadListeningSettings() {
        const context = listeningContext(), generation = ++listening.generation;
        const settings = await api('balance?' + new URLSearchParams(context));
        if (generation !== listening.generation) return;
        element('ft-balance-enabled').checked = settings.enabled;
        for (const [id, key] of [['ft-global-trim', 'song_trim_db'], ['ft-song-trim', 'song_trim_db'], ['ft-tone-trim', 'tone_trim_db']]) element(id).value = settings[key];
        element('ft-global-trim').disabled = element('ft-global-fader').disabled = element('ft-song-volume').disabled = !context.filename;
        element('ft-song-trim').disabled = !context.filename; element('ft-tone-trim').disabled = !context.tone_key;
        listening.baseVolume = settings.song_volume;
        element('ft-song-volume').value = settings.song_volume ?? window.feedBack?.audio?.readSongVolume?.() ?? 80;
        element('ft-section-save').disabled = !context.filename;
    }
    async function updateListeningGain() {
        if (!playing || !ownsRoute()) return;
        const before = playing, request = before.request;
        if (nativeBank) {
            const bank = nativeBank;
            for (const entry of bank.entries) {
                const payload = await prepareRequest(entry.candidate);
                if (nativeBank !== bank || !ownsRoute()) return;
                entry.payload = payload;
                if (playing?.slotId === entry.slotId) {
                    playing.postGain = payload.native_preset.chain[0].postGain ?? 1;
                    playing.request.balance = payload.balance; listening.gain = null;
                    await updateSectionMix();
                } else await desktop().setPostGain(entry.slotId, payload.native_preset.chain[0].postGain ?? 1);
            }
            return;
        }
        const payload = await api(request.customDefinition ? 'designer/prepare' : 'preset', post(request.customDefinition
            ? { ...request.sourceContext, definition: request.customDefinition, title: request.label }
            : { filename: request.filename, arrangement_id: request.arrangementId, tone_key: request.toneKey }));
        if (playing !== before || !ownsRoute()) return;
        before.postGain = payload.native_preset.chain[0].postGain ?? 1;
        request.balance = payload.balance; listening.gain = null;
        await updateSectionMix();
    }
    async function updateSectionMix() {
        const item = following() && !designerPreview && ownsRoute() ? sectionAt() : null;
        const mixer = window.feedBack?.audio;
        const volume = item?.song_volume ?? (inPlayer() ? playing?.request.balance?.song_volume : listening.baseVolume);
        if (listeningContext().filename || listening.songVolume != null) {
            const target = volume ?? mixer?.readSongVolume?.();
            if (target != null && target !== listening.songVolume) {
                listening.songVolume = target;
                await mixer?.applySongVolume?.(target);
                if (preview.active && !inPlayer()) {
                    if(preview.native) await desktop()?.setGain?.('backing',target/100);
                    else if(preview.audio) preview.audio.volume=target/100;
                }
            }
        }
        if (playing && ownsRoute() && typeof desktop()?.setPostGain === 'function') {
            const gain = Math.min(16, playing.postGain * Math.pow(10, (item?.guitar_trim_db || 0) / 20));
            if (gain !== listening.gain) {
                listening.gain = gain;
                try {
                    const result = await desktop().setPostGain(playing.slotId, gain);
                    if (result === false) throw new Error('The guitar listening level could not be applied.');
                } catch (error) { listening.gain = null; listenMessage(error.message); }
            }
        }
        const balance = playing?.request.balance;
        if (!listening.busy && balance) listenMessage(`${balance.enabled ? 'Gentle balancing' : 'Automatic balancing off'} · auto ${Number(balance.auto_db).toFixed(1)} dB · listening trim ${Number(balance.manual_db).toFixed(1)} dB${item ? ' · Section: ' + (item.label || item.id) : ''}${balance.headroom_limited || balance.host_gain_limited ? ' · Gain capped for headroom' : ''}${balance.status === 'unavailable' ? ' · Automatic estimate unavailable: ' + balance.reason : ''}`);
    }
    function drawSections() {
        const list = element('ft-sections'); if (!list) return;
        list.replaceChildren();
        for (const item of listening.ranges) {
            const row = document.createElement('div'); row.className = 'ft-section-row';
            const text = document.createElement('span'); text.textContent = `${item.start.toFixed(1)}–${item.end.toFixed(1)}s · ${item.label || 'Section'}${item.guitar_trim_db != null ? ' · Guitar ' + item.guitar_trim_db + ' dB' : ''}${item.song_volume != null ? ' · Song ' + item.song_volume + '%' : ''}`;
            const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = 'Edit';
            edit.onclick = () => {
                element('ft-section-save').dataset.id = item.id;
                element('ft-section-label').value = item.label || '';
                element('ft-section-start').value = item.start; element('ft-section-end').value = item.end;
                element('ft-section-guitar').value = item.guitar_trim_db ?? '';
                element('ft-section-song').value = item.song_volume ?? '';
                element('ft-section-tone').value = item.rig_id ? 'rig:' + item.rig_id : item.tone_key || '';
            };
            const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Delete';
            remove.onclick = () => listeningAction(async () => {
                const context = listeningContext();
                const value = await api('sections', post({ filename: context.filename, arrangement_id: context.arrangement_id, ranges: listening.ranges.filter(entry => entry.id !== item.id) }));
                listening.ranges = value.ranges; drawSections(); follow();
            });
            row.append(text, edit, remove); list.append(row);
        }
    }
    async function syncListening() {
        const scope = listeningScope();
        if (scope === listening.scope) return;
        listening.scope = scope; listening.ranges = []; drawSections(); drawAuthoredSections();
        const tones = listeningArrangement()?.tone_plans || [];
        setOptions(element('ft-listen-tone'), tones.map(item => [item.tone_key, displayName(item.aliases[0] || item.tone_key)]));
        updateSectionChoices();
        await loadListeningSettings();
        if (!scope) return;
        const [file, arr] = JSON.parse(scope);
        const result = await api('sections?' + new URLSearchParams({ filename: file, arrangement_id: arr }));
        if (listening.scope === scope) { listening.ranges = result.ranges; drawSections(); }
    }
    function updateSectionChoices() {
        const tones = listeningArrangement()?.tone_plans || [], selected = element('ft-section-tone').value;
        setOptions(element('ft-section-tone'), [['', 'Follow song tone'], ...tones.map(item => [item.tone_key, displayName(item.aliases[0] || item.tone_key)]), ...designer.rigs.map(item => ['rig:' + item.id, 'My rig: ' + item.name])], selected);
    }
    async function listeningAction(action) {
        if (listening.busy) return;
        listening.busy = true;
        try { await action(); }
        catch (error) { listenMessage(error.message); }
        finally { listening.busy = false; }
    }
    function bindListening() {
        const panel = element('ft-listening');
        if (!panel) return;
        if (!listening.bound) {
            listening.bound = true;
            const on = (id, event, handler) => element(id).addEventListener(event, handler);
            on('ft-listen-tone', 'change', () => loadListeningSettings().catch(error => listenMessage(error.message)));
            for (const [id, key] of [['ft-balance-enabled', 'enabled'], ['ft-global-trim', 'song_trim_db'], ['ft-song-trim', 'song_trim_db'], ['ft-tone-trim', 'tone_trim_db']]) {
                on(id, 'change', () => {
                    const value = key === 'enabled' ? element(id).checked : Number(element(id).value);
                    const context = listeningContext();
                    // Keep the last fader position even when another gain update is still preparing.
                    listening.settingUpdates = (listening.settingUpdates || Promise.resolve()).then(async () => {
                        await api('balance', post({ ...context, [key]: value }));
                        await updateListeningGain();
                    }).catch(error => listenMessage(error.message));
                });
            }
            on('ft-song-volume', 'change', () => listeningAction(async()=> {
                const context=listeningContext(); if (!context.filename) return;
                const value=Number(element('ft-song-volume').value);
                await api('balance',post({filename:context.filename,song_volume:value}));
                listening.baseVolume=value;
                if (playing?.request.balance && playing.request.filename===context.filename) playing.request.balance.song_volume=value;
                listening.songVolume=null; await updateSectionMix();
            }));
            for (const boundary of ['start', 'end']) on('ft-section-' + boundary + '-now', 'click', () => {
                const time = clock();
                if (Number.isFinite(time)) element('ft-section-' + boundary).value = Math.max(0, time).toFixed(2);
            });
            on('ft-section-new', 'click', () => {
                document.querySelector('.ft-custom-sections').open=true;
                delete element('ft-section-save').dataset.id;
                for (const id of ['label', 'start', 'end', 'guitar', 'song', 'tone']) element('ft-section-' + id).value = '';
            });
            on('ft-section-save', 'click', () => listeningAction(async () => {
                const context = listeningContext(), selection = element('ft-section-tone').value;
                const item = { id: element('ft-section-save').dataset.id || crypto.randomUUID(), label: element('ft-section-label').value,
                    start: Number(element('ft-section-start').value), end: Number(element('ft-section-end').value) };
                if (selection.startsWith('rig:')) item.rig_id = selection.slice(4); else if (selection) item.tone_key = selection;
                if (element('ft-section-guitar').value !== '') item.guitar_trim_db = Number(element('ft-section-guitar').value);
                if (element('ft-section-song').value !== '') item.song_volume = Number(element('ft-section-song').value);
                const ranges = [...listening.ranges.filter(entry => entry.id !== item.id), item];
                const result = await api('sections', post({ filename: context.filename, arrangement_id: context.arrangement_id, ranges }));
                if (nativeBank && result.ranges.some(item => item.rig_id && !nativeBank.entries.some(entry => entry.key === 'rig:' + item.rig_id))) invalidate();
                listening.ranges = result.ranges; drawSections(); follow(); listenMessage('Section saved. Later saved sections take precedence where ranges overlap.');
            }));
            const home = document.createComment('FeedTone listening panel'); panel.before(home);
            const closePanel = () => { home.after(panel); panel.classList.remove('ft-listening-float'); element('ft-listen-close').hidden = true; element('ft-player-button')?.setAttribute('aria-expanded', 'false'); };
            listening.close = closePanel;
            on('ft-listen-close', 'click', closePanel);
            listening.toggle = () => {
                if (panel.classList.contains('ft-listening-float')) { closePanel(); return; }
                const player = element('player'); if (!player) return;
                player.append(panel); panel.classList.add('ft-listening-float'); restoreWindow(panel,'mixer'); element('ft-listen-close').hidden = false;
                element('ft-player-button')?.setAttribute('aria-expanded', 'true');
                panel.querySelector('[role=tab][aria-selected=true]')?.focus();
            };
            window.feedBack?.on?.('screen:changed', closePanel);
            loadListeningSettings().catch(error => listenMessage(error.message));
        }
        const slot = window.feedBack?.ui?.playerControlSlot?.() || element('player-controls');
        if (slot && !element('ft-player-button')) {
            const button = document.createElement('button'); button.id = 'ft-player-button'; button.type = 'button'; button.textContent = 'FeedTone'; button.onclick = listening.toggle;
            button.setAttribute('aria-controls', 'ft-listening'); button.setAttribute('aria-expanded', 'false');
            button.className = 'px-3 py-1.5 rounded-lg text-xs'; slot.append(button);
        }
        if (listeningScope() !== listening.scope) syncListening().catch(error => listenMessage(error.message));
        if (document.activeElement !== element('ft-song-volume')) element('ft-song-volume').value = listening.baseVolume ?? window.feedBack?.audio?.readSongVolume?.() ?? 80;
        updateSectionMix().catch(error => listenMessage(error.message));
    }
    function activateTabs(buttons, pages, key, attribute) {
        for (const button of buttons) {
            const selected = button.getAttribute(attribute) === key;
            button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
        }
        const paneKey = attribute === 'data-ft-view' && key === 'sections' ? 'mix' : key;
        for (const page of pages) page.hidden = page.getAttribute(attribute === 'data-ft-view' ? 'data-ft-pane' : 'data-ft-panel-page') !== paneKey;
        if (attribute === 'data-ft-view' && key !== 'rig') {
            element('ft-mix-view').setAttribute('aria-labelledby', key === 'sections' ? 'ft-tab-sections' : 'ft-tab-mix');
            activateTabs([...document.querySelectorAll('[data-ft-panel-tab]')], [...document.querySelectorAll('[data-ft-panel-page]')], key, 'data-ft-panel-tab');
        }
        if (attribute === 'data-ft-view') for (const button of document.querySelectorAll('[data-ft-workspace-view]')) button.setAttribute('aria-current',button.dataset.ftWorkspaceView===key?'page':'false');
        element('rst-preview').hidden = attribute === 'data-ft-view' ? key !== 'rig' : element('rst-preview').hidden;
    }
    function bindTabs(buttonSelector, pageSelector, attribute) {
        const buttons = [...document.querySelectorAll(buttonSelector)], pages = [...document.querySelectorAll(pageSelector)];
        for (const button of buttons) {
            button.addEventListener('click', () => activateTabs(buttons, pages, button.getAttribute(attribute), attribute));
            button.addEventListener('keydown', event => {
                const index = buttons.indexOf(button);
                const next = event.key === 'ArrowRight' ? (index + 1) % buttons.length : event.key === 'ArrowLeft' ? (index + buttons.length - 1) % buttons.length : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : null;
                if (next === null) return;
                event.preventDefault(); buttons[next].click(); buttons[next].focus();
            });
        }
    }
    function studioView(key) {
        activateTabs([...document.querySelectorAll('[data-ft-view]')], [...document.querySelectorAll('[data-ft-pane]')], key, 'data-ft-view');
    }
    function positionWindow(surface, key, x, y, persist = true) {
        const bounds = surface.getBoundingClientRect(), parent = surface.offsetParent?.getBoundingClientRect() || {left:0,top:0};
        const left = Math.max(8, Math.min(innerWidth - bounds.width - 8, x));
        const top = Math.max(8, Math.min(innerHeight - Math.min(bounds.height, innerHeight - 16) - 8, y));
        Object.assign(surface.style, {left: `${left-parent.left}px`, top: `${top-parent.top}px`, right:'auto', bottom:'auto'});
        if (persist) try { localStorage.setItem('feedtone_window_' + key, JSON.stringify({x:left,y:top})); } catch (_) {}
    }
    function restoreWindow(surface, key) {
        try {
            const position = JSON.parse(localStorage.getItem('feedtone_window_' + key));
            if (Number.isFinite(position?.x) && Number.isFinite(position?.y)) positionWindow(surface, key, position.x, position.y, false);
        } catch (_) {}
    }
    function centerWindow(surface, key) {
        if (!surface) return;
        const rect = surface.getBoundingClientRect(); positionWindow(surface,key,(innerWidth-rect.width)/2,(innerHeight-rect.height)/2);
    }
    function bindWindowDrag(handle, getSurface, key) {
        handle.tabIndex = 0; handle.setAttribute('aria-label','Move FeedTone window: drag, or use arrow keys. Home centers.');
        let drag = null;
        const controls = target => target.closest('button,input,select,a,label');
        handle.addEventListener('pointerdown', event => {
            const surface = getSurface(); if (!surface) return;
            event.stopPropagation();
            if (event.button !== 0 || controls(event.target)) return;
            const rect = surface.getBoundingClientRect(); drag = {surface,x:event.clientX,y:event.clientY,left:rect.left,top:rect.top};
            event.preventDefault(); handle.focus({preventScroll:true});
            handle.setPointerCapture(event.pointerId); handle.classList.add('ft-dragging');
        });
        handle.addEventListener('pointermove', event => {
            if (drag) { event.stopPropagation(); positionWindow(drag.surface,key,drag.left+event.clientX-drag.x,drag.top+event.clientY-drag.y,false); }
        });
        const finish = event => {
            if (drag) event?.stopPropagation();
            if (drag && getSurface() === drag.surface && drag.surface.isConnected) { const rect=drag.surface.getBoundingClientRect(); positionWindow(drag.surface,key,rect.left,rect.top); }
            drag=null; handle.classList.remove('ft-dragging');
        };
        for (const event of ['pointerup','pointercancel','lostpointercapture']) handle.addEventListener(event,finish);
        handle.addEventListener('keydown', event => {
            const surface=getSurface(); if (!surface || event.target!==handle) return;
            if (event.key==='Home') { event.stopPropagation(); event.preventDefault(); centerWindow(surface,key); return; }
            if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
            event.stopPropagation(); event.preventDefault(); const rect=surface.getBoundingClientRect(),step=event.shiftKey?4:16;
            positionWindow(surface,key,rect.left+(event.key==='ArrowRight'?step:event.key==='ArrowLeft'?-step:0),rect.top+(event.key==='ArrowDown'?step:event.key==='ArrowUp'?-step:0));
        });
        handle.addEventListener('dblclick', event => { if (!controls(event.target)) centerWindow(getSurface(),key); });
    }
    function mountSidebar() {
        const nav=element('v3-nav'), existing=element('ft-sidebar-link');
        if(existing) { existing.setAttribute('aria-current', !presentation.overlay && !!element('feedtone-panel')?.getClientRects().length ? 'page':'false'); return; }
        if (!nav) return;
        const link=document.createElement('a'); link.id='ft-sidebar-link'; link.href='#/plugin-feedtone';
        link.className='flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-fb-textDim hover:text-fb-text hover:bg-fb-card/50 transition-colors';
        link.innerHTML='<span class="ft-nav-icon" aria-hidden="true">▣</span><span class="v3-nav-label">FeedTone</span>';
        link.addEventListener('click', event=>{event.preventDefault();closePlayerDesigner();listening.close?.();window.showScreen?.('plugin-feedtone');});
        const anchor=element('v3-nav-rig-builder') || nav.querySelector('[data-v3-nav="saved"]');
        if (anchor) anchor.after(link); else nav.append(link);
    }
    async function refreshUpdates(path='updates', body) {
        try {
            const state=await api(path,body ? post(body) : path.endsWith('/check') || path.endsWith('/install') ? post({}) : undefined);
            const automatic=element('ft-auto-update'); automatic.checked=state.automatic; automatic.disabled=state.status==='pending';
            element('ft-check-update').disabled=['checking','downloading','pending'].includes(state.status);
            element('ft-install-update').hidden=!state.update_available || ['checking','downloading','pending'].includes(state.status);
            element('ft-update-status').textContent=state.status==='pending' ? `v${state.pending_version} ready — installs after FeedBack closes.`
                : state.status==='error' ? `Update check: ${state.error}` : state.status==='checking' ? 'Checking GitHub…'
                : state.status==='downloading' ? 'Downloading and verifying update…'
                : state.update_available ? `v${state.remote_version} available` : `v${state.local_version} · Up to date`;
            if (state.previous_error) element('ft-update-status').textContent += ` · Previous install: ${state.previous_error}`;
            if (['checking','downloading'].includes(state.status)) setTimeout(()=>refreshUpdates(),1500);
        } catch (error) { element('ft-update-status').textContent=`Updates unavailable: ${error.message}`; }
    }
    async function openPlayerDesigner(slot) {
        const player = element('player'); if (!player) return;
        listening.close?.();
        studioView('rig');
        if (!presentation.overlay) {
            const root = element('feedtone-panel'), home = document.createComment('FeedTone studio home'); root.before(home);
            const overlay = document.createElement('div'); overlay.className = 'ft-designer-overlay'; overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-label', 'FeedTone rig designer'); overlay.setAttribute('aria-modal', 'false');
            player.append(overlay); overlay.append(root); presentation.overlay = { element: overlay, home, root };
            restoreWindow(overlay, 'designer'); element('ft-window-reset').hidden = false;
            element('ft-studio-close').hidden = false;
        }
        const request = playing?.request;
        if (!designer.dirty && designer.catalog && request) {
            if (request.sectionRig) {
                const rig = designer.rigs.find(item => item.id === request.sectionRig);
                if (rig) { designer.context = null; designer.rigId = rig.id; designer.draft = copy(rig.definition); designer.version++; designer.live = null; drawDraft(); }
            } else if (request.arrangementId && designer.song) {
                element('rst-arrangement').value = request.arrangementId; await loadEditorArrangement(request.toneKey);
            }
        }
        if (slot && designer.catalog?.slots.some(item => item.id === slot)) { designer.selectedSlot = slot; drawSlots(); }
        element('ft-studio-close').focus();
    }
    function closePlayerDesigner() {
        const overlay = presentation.overlay; if (!overlay) return;
        overlay.home.after(overlay.root); overlay.home.remove(); overlay.element.remove(); presentation.overlay = null;
        element('ft-studio-close').hidden = true; element('ft-window-reset').hidden = true; element('ft-player-button')?.focus();
    }
    function syncToneFader() {
        const volume = element('rst-volume'), fader = element('ft-tone-fader');
        if (!volume || !fader) return;
        const value = Number(volume.value), finite = volume.value !== '' && Number.isFinite(value);
        fader.min = Math.min(-36, finite ? value : -36); fader.max = Math.max(0, finite ? value : 0);
        fader.disabled = !finite; if (finite) fader.value = value;
    }
    async function updateMeters() {
        const root = element('feedtone-panel');
        if (!root?.getClientRects().length || root.hidden || element('ft-rig-view')?.hidden || presentation.meterBusy) return;
        presentation.meterBusy = true;
        try {
            const levels = await desktop()?.getLevels?.();
            for (const key of ['input', 'output']) {
                const value = levels?.[key + 'Level'], valid = typeof value === 'number' && Number.isFinite(value) && value >= 0;
                const db = valid && value > 0 ? Math.max(-60, Math.min(0, 20 * Math.log10(value))) : -60;
                element('ft-meter-' + key).value = db;
                element('ft-meter-' + key + '-value').textContent = valid ? db <= -60 ? '−∞' : `${db.toFixed(0)} dB` : '—';
                element('ft-meter-' + key).dataset.clipping = String(valid && value >= .99);
            }
        } catch (_) {
            for (const key of ['input', 'output']) { element('ft-meter-' + key).value = -60; element('ft-meter-' + key + '-value').textContent = '—'; }
        } finally { presentation.meterBusy = false; }
    }
    function bindPresentation() {
        const root = element('feedtone-panel'); if (!root) return;
        if (!presentation.bound) {
            presentation.bound = true;
            for (const button of document.querySelectorAll('[data-ft-workspace-view]')) button.addEventListener('click',()=>studioView(button.dataset.ftWorkspaceView));
            element('ft-back-feedback').addEventListener('click',()=>window.showScreen?.('v3-home'));
            element('ft-workspace-rigs').addEventListener('click',()=>element('ft-library-shortcut').click());
            bindWindowDrag(root.querySelector('.ft-header'),()=>presentation.overlay?.element,'designer');
            bindWindowDrag(element('ft-listening').querySelector('.ft-listening-title'),()=>element('ft-listening').classList.contains('ft-listening-float')?element('ft-listening'):null,'mixer');
            element('ft-window-reset').addEventListener('click',()=>centerWindow(presentation.overlay?.element,'designer'));
            window.addEventListener('resize',()=>{for(const [surface,key] of [[presentation.overlay?.element,'designer'],[element('ft-listening').classList.contains('ft-listening-float')?element('ft-listening'):null,'mixer']]) if(surface){const r=surface.getBoundingClientRect();positionWindow(surface,key,r.left,r.top,false);}});
            element('ft-check-update').addEventListener('click',()=>refreshUpdates('updates/check'));
            element('ft-install-update').addEventListener('click',()=>refreshUpdates('updates/install'));
            element('ft-auto-update').addEventListener('change',event=>refreshUpdates('updates/settings',{automatic:event.target.checked}));
            refreshUpdates(); setInterval(()=>refreshUpdates(),21600000);
            element('ft-tone-fader').addEventListener('input', event => { element('rst-volume').value = event.target.value; element('rst-volume').dispatchEvent(new Event('input', {bubbles:true})); });
            element('rst-volume').addEventListener('input', syncToneFader);
            element('ft-studio-balance').addEventListener('change', event => { const balance = element('ft-balance-enabled'); balance.checked = event.target.checked; balance.dispatchEvent(new Event('change', {bubbles:true})); });
            element('ft-equipment-search').addEventListener('input', drawEquipment);
            for (const button of document.querySelectorAll('[data-ft-gear]')) button.addEventListener('click', () => {
                presentation.gearFilter = button.dataset.ftGear;
                for (const item of document.querySelectorAll('[data-ft-gear]')) item.setAttribute('aria-pressed', String(item === button));
                drawEquipment();
            });
            setInterval(updateMeters, 100);
            element('ft-toggle-empty').addEventListener('click', () => { presentation.showEmpty = !presentation.showEmpty; element('ft-toggle-empty').setAttribute('aria-pressed', String(presentation.showEmpty)); element('ft-toggle-empty').textContent = presentation.showEmpty ? 'Hide empty slots' : '+ Add device'; if (designer.draft) drawSlots(); });
            const details=document.querySelector('.ft-edit-details'), controls=details.querySelector('.ft-control-area');
            details.insertBefore(details.querySelector('.ft-save-bar'),controls);details.insertBefore(details.querySelector('.ft-library'),controls);
            bindTabs('[data-ft-view]', '[data-ft-pane]', 'data-ft-view');
            bindTabs('[data-ft-panel-tab]', '[data-ft-panel-page]', 'data-ft-panel-tab');
            element('ft-open-designer').addEventListener('click', () => openPlayerDesigner().catch(error => listenMessage(error.message)));
            element('ft-studio-close').addEventListener('click', closePlayerDesigner);
            element('ft-library-shortcut').addEventListener('click', () => { studioView('rig'); document.querySelector('.ft-edit-details').open = true; element('ft-library').scrollIntoView({ block: 'nearest' }); element('rst-library').focus(); });
            const fader = element('ft-global-fader'), trim = element('ft-global-trim');
            fader.addEventListener('input', () => { trim.value = fader.value; });
            fader.addEventListener('change', () => { trim.value = fader.value; trim.dispatchEvent(new Event('change', { bubbles: true })); });
            trim.addEventListener('input', () => { fader.value = trim.value; });
            element('ft-song-volume').addEventListener('input', () => { element('ft-song-volume-readout').value = element('ft-song-volume').value; });
            document.addEventListener('keydown', event => {
                if (event.key !== 'Escape') return;
                if (!element('rst-device-browser').hidden) { element('rst-device-browser').hidden = true; event.preventDefault(); }
                else if (presentation.overlay) { closePlayerDesigner(); event.preventDefault(); }
                else if (element('ft-listening').classList.contains('ft-listening-float')) { listening.close?.(); element('ft-player-button')?.focus(); event.preventDefault(); }
            });
            window.feedBack?.on?.('screen:changed', closePlayerDesigner);
        }
        bindWorkspace(); mountSidebar();
        if (!presentation.overlay && innerWidth>=1100 && innerHeight>=700 && !presentation.detailsOpened) {document.querySelector('.ft-edit-details').open=true;presentation.detailsOpened=true;}
        if (document.activeElement !== element('ft-studio-balance')) element('ft-studio-balance').checked = element('ft-balance-enabled').checked;
        if (document.activeElement !== element('ft-global-fader')) element('ft-global-fader').value = element('ft-global-trim').value;
        element('ft-song-volume-readout').value = element('ft-song-volume').value;
        const identity = playing?.request.identity || '';
        if (presentation.liveIdentity !== identity && designer.catalog) {
            presentation.liveIdentity = identity;
            element('ft-live-tone').textContent = displayName(playing?.request.label || 'No active tone');
            const chain = element('ft-live-chain'); chain.replaceChildren();
            for (const id of playing?.request.definition?.ChainOrder || designer.catalog.slots.map(slot=>slot.id)) {
                const slot=designer.catalog.slots.find(slot=>slot.id===id);
                const gear = playing?.request.definition?.GearList?.[slot.id]; if (!gear) continue;
                const device = designer.catalog.devices.find(item => item.key === (gear.Key || gear.PedalKey));
                const button = document.createElement('button'); button.type = 'button'; button.className = 'ft-live-device';
                const label = document.createElement('small'); label.textContent = slotName(slot.id);
                const name = document.createElement('strong'); name.textContent = displayName(device?.name || gear.Key);
                button.append(label, face(device), name); button.addEventListener('click', () => openPlayerDesigner(slot.id).catch(error => listenMessage(error.message))); chain.append(button);
            }
        }
    }
    function bind() {
        const bus = window.feedBack || window.slopsmith;
        if (!bus?.on) { setTimeout(bind, 250); return; }
        bus.on('song:loaded', () => { invalidate(); filename = ''; pending = null; song = null; refresh(); });
        for (const name of ['song:ready', 'arrangement:changed']) bus.on(name, () => { invalidate(); refresh(); follow(); });
        for (const name of ['tone:changed', 'tone-changed', 'rig:tone-changed']) bus.on(name, follow);
        registerHost(); restoreSelection(); refresh();
    }
    api('status').then(value => {
        const coverage = value.engine || {};
        coverageText = `${coverage.devices || 0} devices`;
        render();
    }).catch(error => { coverageText = error.message; render(); });
    bind();
    setInterval(() => { render(); registerHost(); restoreSelection(); if (enabled) refresh(); }, 80);
    setInterval(follow, 20);
})();
