<script lang="ts">
	// Writing one spool to one tag.
	//
	// The dialog follows ConfirmDialog's structure (window-level Escape, backdrop
	// as a sibling button, role="dialog" + tabindex="-1") so it behaves like every
	// other modal here and stays clean under svelte-check's a11y rules.
	//
	// Writing is a single request that stays open while the reader waits for a
	// tag, so "waiting" here is literally the request in flight. Cancelling aborts
	// it, which lets the server disarm the reader.
	import Button from '../Button.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { previewTag, writeTag, NfcError, type OperationResult, type TagPreview } from '$lib/api/nfc';
	import { nfc } from '$lib/stores/nfc.svelte';
	import { settings } from '$lib/stores/settings.svelte';

	interface Props {
		open: boolean;
		spoolId: number | null;
		/** Shown in the heading so the user knows which spool is being written. */
		spoolName?: string;
		onclose: () => void;
		/** Called after a successful write, for callers that continue a flow. */
		ondone?: (result: OperationResult) => void;
	}

	let { open, spoolId, spoolName = '', onclose, ondone }: Props = $props();

	type Phase = 'idle' | 'waiting' | 'done' | 'error';

	let format = $state('');
	let preview = $state<TagPreview | null>(null);
	let phase = $state<Phase>('idle');
	let result = $state<OperationResult | null>(null);
	let errorText = $state('');
	let controller: AbortController | null = null;
	let release: (() => void) | null = null;

	let dialog = $state<HTMLDivElement | null>(null);
	let opener: HTMLElement | null = null;

	const chosen = $derived(nfc.formats.find((f) => f.key === format) ?? null);
	const busy = $derived(phase === 'waiting');
	const canWrite = $derived(!!spoolId && nfc.available && !busy && !!format);

	$effect(() => {
		if (open) {
			opener ??= document.activeElement as HTMLElement | null;
			dialog?.focus();
		} else if (opener) {
			opener.focus();
			opener = null;
		}
	});

	// Opening resets to the configured default rather than whatever was picked
	// last time: the default is a deliberate setting, and a stale choice from a
	// previous spool is a quiet way to write the wrong format.
	$effect(() => {
		if (!open) return;
		phase = 'idle';
		result = null;
		errorText = '';
		format = settings.nfcDefaultFormat || nfc.formats[0]?.key || '';
	});

	// Re-render the preview whenever the spool or the format changes, so the
	// recommendation always describes what would actually be written.
	$effect(() => {
		const id = spoolId;
		const key = format;
		if (!open || !id || !key) {
			preview = null;
			return;
		}
		let stale = false;
		previewTag(id, key)
			.then((p) => {
				if (!stale) preview = p;
			})
			.catch(() => {
				if (!stale) preview = null;
			});
		return () => {
			stale = true;
		};
	});

	function close() {
		if (busy) cancel();
		onclose();
	}

	function cancel() {
		controller?.abort();
		controller = null;
		release?.();
		release = null;
		phase = 'idle';
	}

	async function write() {
		if (!spoolId || !format) return;
		phase = 'waiting';
		errorText = '';
		result = null;
		controller = new AbortController();
		release = nfc.claim();
		try {
			const outcome = await writeTag(spoolId, format, { signal: controller.signal });
			result = outcome;
			// This tag is now accounted for; without this it would be announced as a
			// fresh discovery the moment the reader notices it again.
			if (outcome.uid) nfc.suppress(outcome.uid);
			if (outcome.ok) {
				phase = 'done';
				ondone?.(outcome);
			} else {
				phase = 'error';
				errorText = outcome.message;
			}
		} catch (e) {
			if (controller?.signal.aborted) return;
			phase = 'error';
			errorText = e instanceof NfcError ? e.message : String(e);
		} finally {
			release?.();
			release = null;
			controller = null;
		}
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (open && e.key === 'Escape') close();
	}}
/>

{#if open}
	<div class="overlay">
		<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
		<div
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby="nfc-write-title"
			tabindex="-1"
			bind:this={dialog}
		>
			<div class="head">
				<span class="title" id="nfc-write-title">
					{m['nfc.writeAction']()}{spoolName ? ` — ${spoolName}` : ''}
				</span>
				<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
			</div>

			<div class="body">
				{#if !nfc.enabled}
					<p class="warn">{m['nfc.reader.disabled']()}</p>
				{:else if !nfc.connected}
					<p class="warn">{nfc.error || m['nfc.reader.offline']()}</p>
				{/if}

				<div class="field">
					<label class="lbl" for="nfc-format">{m['nfc.format.label']()}</label>
					<select id="nfc-format" bind:value={format} disabled={busy}>
						{#each nfc.formats as fmt (fmt.key)}
							<option value={fmt.key}>{fmt.label}</option>
						{/each}
					</select>
				</div>
				{#if chosen}
					<p class="desc">{chosen.description}</p>
				{/if}

				{#if preview}
					{#if preview.writes_tag}
						<p class="size">{m['nfc.payloadSize']({ size: preview.size })}</p>
					{:else}
						<p class="size">{m['nfc.nothingWritten']()}</p>
					{/if}

					{#if preview.notes.length}
						<div class="notes">
							<div class="notes-title">{m['nfc.notesTitle']()}</div>
							{#each preview.notes as note (note)}
								<p>{note}</p>
							{/each}
						</div>
					{/if}

					{#if preview.writes_tag}
						<div class="chips-head">{m['nfc.recommendedTags']()}</div>
						<ul class="chips">
							{#each preview.recommended as chip (chip.name)}
								<li class:no={!chip.fits}>
									<span class="chip-name">{chip.name}</span>
									<span class="chip-note">
										{#if chip.fits}
											{m['nfc.chipFits']({ headroom: chip.headroom })}
										{:else}
											{m['nfc.chipTooSmall']({ over: -chip.headroom })}
										{/if}
									</span>
								</li>
							{/each}
						</ul>
						<p class="hint">{m['nfc.recommendedHint']()}</p>
					{/if}
				{/if}

				{#if phase === 'waiting'}
					<div class="status waiting">
						<div class="status-title">{m['nfc.armed']()}</div>
						<p>{m['nfc.armedHint']()}</p>
					</div>
				{:else if phase === 'done' && result}
					<div class="status ok">
						<div class="status-title">
							{#if result.written_bytes}
								{m['nfc.written']({ bytes: result.written_bytes })}
							{:else}
								{m['nfc.erase.done']()}
							{/if}
						</div>
						<p class="mono">{m['nfc.uid']()}: {result.uid}</p>
						{#if result.bound}<p>{m['nfc.bound']()}</p>{/if}
					</div>
				{:else if phase === 'error'}
					<div class="status bad">
						<div class="status-title">{errorText}</div>
					</div>
				{/if}
			</div>

			<div class="foot">
				{#if phase === 'waiting'}
					<Button variant="outline" onclick={cancel}>{m['nfc.cancel']()}</Button>
				{:else if phase === 'done'}
					<Button onclick={close}>{m['buttons.close']()}</Button>
				{:else}
					<Button variant="outline" onclick={close}>{m['buttons.cancel']()}</Button>
					<Button disabled={!canWrite} onclick={write}>
						{phase === 'error' ? m['nfc.retry']() : m['nfc.writeAction']()}
					</Button>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 10vh 16px 16px;
	}
	.backdrop {
		position: fixed;
		inset: 0;
		border: none;
		margin: 0;
		padding: 0;
		background: transparent;
		cursor: default;
	}
	.dialog {
		position: relative;
		z-index: 1;
		width: 460px;
		max-width: 100%;
		max-height: 80vh;
		display: flex;
		flex-direction: column;
		background: var(--bg);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-xl);
		box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
		overflow: hidden;
	}
	.head {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 16px 20px 0;
	}
	.title {
		font-weight: 700;
		font-size: 15px;
	}
	.x {
		margin-left: auto;
		color: var(--text-dim);
		cursor: pointer;
		padding: 4px 8px;
		background: none;
		border: none;
		display: inline-flex;
	}
	.x:hover {
		color: var(--text);
	}
	.body {
		padding: 12px 20px 4px;
		font-size: 13px;
		line-height: 1.5;
		color: var(--text-2);
		overflow-y: auto;
	}
	.body p {
		margin: 0 0 8px;
	}
	.field {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 6px;
	}
	.lbl {
		flex: 1;
		font-size: 13px;
		color: var(--text);
	}
	select {
		min-width: 200px;
		font: inherit;
		padding: 5px 8px;
		color: var(--text);
		background: var(--bg-2, var(--bg));
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
	}
	.desc {
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.size {
		font-size: 12px;
		color: var(--text-dim);
	}
	.warn {
		color: var(--danger, #e5484d);
	}
	.notes {
		border-left: 2px solid var(--border-strong);
		padding: 2px 0 2px 10px;
		margin: 0 0 10px;
	}
	.notes-title {
		font-weight: 600;
		color: var(--text);
		margin-bottom: 4px;
	}
	.chips-head {
		font-weight: 600;
		color: var(--text);
		margin: 10px 0 6px;
	}
	.chips {
		list-style: none;
		margin: 0 0 6px;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 3px;
	}
	.chips li {
		display: flex;
		gap: 8px;
		align-items: baseline;
	}
	.chips li.no {
		color: var(--text-dim);
		text-decoration-line: line-through;
		text-decoration-color: var(--border-strong);
	}
	.chip-name {
		font-weight: 600;
		min-width: 88px;
	}
	.chip-note {
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.hint {
		font-size: 11.5px;
		color: var(--text-dim);
	}
	.status {
		margin-top: 12px;
		padding: 10px 12px;
		border-radius: var(--radius);
		border: 1px solid var(--border-strong);
	}
	.status-title {
		font-weight: 600;
		color: var(--text);
	}
	.status.ok {
		border-color: var(--ok, #30a46c);
	}
	.status.bad {
		border-color: var(--danger, #e5484d);
	}
	.mono {
		font-family: var(--font-mono, monospace);
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 16px 20px 18px;
		border-top: 1px solid var(--border);
	}
</style>
