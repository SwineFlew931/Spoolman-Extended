<script lang="ts">
	// Raised when a tag is tapped and nothing was expecting one.
	//
	// What it offers depends on what the tag turns out to be. A tag bound to a
	// spool can be opened, rewritten or erased; an unbound one can only be erased,
	// because there is no spool in hand to write and guessing at one would be
	// worse than saying so.
	import Button from '../Button.svelte';
	import ConfirmDialog from '../ConfirmDialog.svelte';
	import X from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { eraseTag, lookupUid, type TagEvent, type UidOwner } from '$lib/api/nfc';
	import { nfc } from '$lib/stores/nfc.svelte';
	import { toasts } from '$lib/stores/toasts.svelte';

	interface Props {
		tag: TagEvent | null;
		onclose: () => void;
		/** Hand the bound spool back so the caller can open the write dialog on it. */
		onoverwrite: (spoolId: number, spoolName: string) => void;
	}

	let { tag, onclose, onoverwrite }: Props = $props();

	let owner = $state<UidOwner | null>(null);
	let confirmErase = $state(false);
	let erasing = $state(false);

	let dialog = $state<HTMLDivElement | null>(null);
	let opener: HTMLElement | null = null;

	const open = $derived(!!tag?.uid);

	$effect(() => {
		if (open) {
			opener ??= document.activeElement as HTMLElement | null;
			dialog?.focus();
		} else if (opener) {
			opener.focus();
			opener = null;
		}
	});

	$effect(() => {
		const uid = tag?.uid;
		if (!uid) {
			owner = null;
			return;
		}
		let stale = false;
		lookupUid(uid)
			.then((o) => {
				if (!stale) owner = o;
			})
			.catch(() => {
				if (!stale) owner = null;
			});
		return () => {
			stale = true;
		};
	});

	// Only the shapes this fork can write are named; anything else is reported by
	// its record type rather than guessed at.
	function describe(event: TagEvent): string {
		const type = event.records?.[0]?.type ?? '';
		if (type === 'application/opentag3d') return 'OpenTag3D';
		if (type === 'application/json') return 'OpenSpool';
		if (type === 'urn:nfc:wkt:T') return 'nfc2klipper';
		return type;
	}

	function close() {
		if (!erasing) onclose();
	}

	async function doErase() {
		if (!tag?.uid) return;
		erasing = true;
		const release = nfc.claim();
		try {
			const result = await eraseTag({ unbind: true });
			if (result.uid) nfc.suppress(result.uid);
			if (result.ok) {
				toasts.success(m['nfc.erase.done']());
			} else {
				toasts.error(result.message);
			}
		} catch (e) {
			toasts.error(String(e));
		} finally {
			release();
			erasing = false;
			confirmErase = false;
			onclose();
		}
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (open && !confirmErase && e.key === 'Escape') close();
	}}
/>

{#if open && tag}
	<div class="overlay">
		<button class="backdrop" tabindex="-1" aria-hidden="true" onclick={close}></button>
		<div
			class="dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby="nfc-found-title"
			tabindex="-1"
			bind:this={dialog}
		>
			<div class="head">
				<span class="title" id="nfc-found-title">{m['nfc.tagFound.title']()}</span>
				<button class="x" onclick={close} aria-label={m['buttons.close']()}><X size={16} /></button>
			</div>

			<div class="body">
				<p class="mono">{m['nfc.uid']()}: {tag.uid}</p>
				{#if owner && !owner.free}
					<p>{m['nfc.tagFound.known']({ name: owner.spool_name })}</p>
				{:else if tag.blank}
					<p>{m['nfc.tagFound.blank']()}</p>
				{:else}
					<p>{m['nfc.tagFound.unknownData']({ format: describe(tag) })}</p>
				{/if}
			</div>

			<div class="foot">
				<Button variant="outline" onclick={() => (confirmErase = true)}>
					{m['nfc.erase.action']()}
				</Button>
				{#if owner && owner.spool_id !== null}
					<Button variant="outline" onclick={() => onoverwrite(owner!.spool_id!, owner!.spool_name)}>
						{m['nfc.overwrite']()}
					</Button>
					<Button
						onclick={() => {
							const id = owner!.spool_id!;
							onclose();
							goto(resolve(`/?sel=spool:${id}` as '/'));
						}}
					>
						{m['nfc.goToSpool']()}
					</Button>
				{/if}
			</div>
		</div>
	</div>
{/if}

<ConfirmDialog
	open={confirmErase}
	title={m['nfc.erase.title']()}
	lines={owner && !owner.free
		? [m['nfc.erase.body'](), m['nfc.erase.unbindBody']({ name: owner.spool_name })]
		: [m['nfc.erase.body']()]}
	confirmLabel={m['nfc.erase.confirm']()}
	busy={erasing}
	onconfirm={doErase}
	onclose={() => (confirmErase = false)}
/>

<style>
	.overlay {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		z-index: 60;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding: 12vh 16px 16px;
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
		width: 440px;
		max-width: 100%;
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
	}
	.body p {
		margin: 0 0 8px;
	}
	.mono {
		font-family: var(--font-mono, monospace);
	}
	.foot {
		display: flex;
		justify-content: flex-end;
		gap: 8px;
		padding: 16px 20px 18px;
	}
</style>
