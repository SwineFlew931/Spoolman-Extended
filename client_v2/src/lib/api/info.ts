import { getJson } from './http';

// Backend build/runtime info, served once at startup from GET /info.
export interface Info {
	/** The upstream Spoolman version. Never carries a fork's local segment. */
	version: string;
	/** Set only on a fork build, e.g. "0.26.1+ext.1". Null upstream. */
	fork_version?: string | null;
	debug_mode: boolean;
	automatic_backups: boolean;
	data_dir: string;
	backups_dir: string;
	db_type: string;
	external_db_name: string;
	git_commit?: string;
	build_date?: string;
}

export function getInfo(): Promise<Info> {
	return getJson<Info>('/info');
}
