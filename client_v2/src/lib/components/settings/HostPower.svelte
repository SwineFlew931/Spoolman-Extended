<script lang="ts">
	// Restart or shut down the machine Spoolman runs on.
	//
	// Spoolman itself has no way to do this, which bites hardest in the one
	// situation where reaching a terminal is least convenient: the server is
	// misbehaving, or an SD card is about to come out and the filesystem should be
	// stopped cleanly first.
	//
	// It goes through the NFC writer service rather than Spoolman, because
	// Spoolman's Python is kept stock and that service already runs as the
	// operator's own user. The privilege behind it is a sudoers drop-in granting
	// exactly `systemctl reboot` and `systemctl poweroff`.
	//
	// The whole section hides itself unless the host says it will accept an
	// action, so an install without the drop-in shows no button rather than one
	// that can only fail.
	import Card from '../Card.svelte';
	import SettingRow from './SettingRow.svelte';
	import Button from '../Button.svelte';
	import ConfirmDialog from '../ConfirmDialog.svelte';
	import {
		getPowerActions,
		runPowerAction,
		type PowerAction,
		type PowerActions
	} from '$lib/api/nfcWriter';
	import * as m from '$lib/paraglide/messages';

	let actions = $state<PowerActions | null>(null);
	let asking = $state<PowerAction | null>(null);
	let busy = $state(false);
	// What the server said as it went away. Kept on screen in place of the
	// buttons, because the usual feedback route -- a request that succeeds and a
	// list that refreshes -- is exactly what stops working here.
	let outcome = $state('');
	let failure = $state('');

	$effect(() => {
		let live = true;
		getPowerActions()
			.then((a) => {
				if (live) actions = a;
			})
			.catch(() => {
				// No writer service, or no permission to ask. Either way there is
				// nothing to offer and nothing worth saying about it here.
				if (live) actions = null;
			});
		return () => {
			live = false;
		};
	});

	const copy = {
		reboot: {
			label: m['host.reboot.label'],
			desc: m['host.reboot.desc'],
			action: m['host.reboot.action'],
			title: m['host.reboot.title'],
			body: m['host.reboot.body'],
			confirm: m['host.reboot.confirm'],
			accepted: m['host.reboot.accepted']
		},
		shutdown: {
			label: m['host.shutdown.label'],
			desc: m['host.shutdown.desc'],
			action: m['host.shutdown.action'],
			title: m['host.shutdown.title'],
			body: m['host.shutdown.body'],
			confirm: m['host.shutdown.confirm'],
			accepted: m['host.shutdown.accepted']
		}
	} as const;

	let offered = $derived(
		(['reboot', 'shutdown'] as PowerAction[]).filter((a) => actions?.[a])
	);

	async function run(action: PowerAction) {
		busy = true;
		failure = '';
		try {
			await runPowerAction(action);
			// Deliberately not awaiting the machine actually going down: it will
			// never answer again, so the accepted request is the last fact there is.
			outcome = copy[action].accepted();
		} catch (err) {
			failure = m['host.failed']({ error: (err as Error)?.message ?? String(err) });
		} finally {
			busy = false;
			asking = null;
		}
	}
</script>

{#if offered.length}
	<div class="sec-label">{m['host.tab']()}</div>
	<Card divided>
		{#if outcome}
			<div class="outcome">{outcome}</div>
		{:else}
			{#each offered as action (action)}
				<SettingRow title={copy[action].label()} desc={copy[action].desc()}>
					<Button variant="outline" disabled={busy} onclick={() => (asking = action)}>
						{copy[action].action()}
					</Button>
				</SettingRow>
			{/each}
			{#if failure}
				<div class="failure">{failure}</div>
			{/if}
		{/if}
	</Card>

	<ConfirmDialog
		open={asking !== null}
		title={asking ? copy[asking].title() : ''}
		lines={asking ? [copy[asking].body()] : []}
		confirmLabel={asking ? copy[asking].confirm() : ''}
		{busy}
		onconfirm={() => asking && run(asking)}
		onclose={() => {
			if (!busy) asking = null;
		}}
	/>
{/if}

<style>
	/* Matches the section labels on the settings page; the page's own rule is
	   scoped to it, so it cannot reach in here. */
	.sec-label {
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--text-dim);
		padding: 22px 0 8px;
	}
	.outcome,
	.failure {
		padding: 12px 14px;
		font-size: 13px;
	}
	.failure {
		color: var(--danger);
	}
</style>
