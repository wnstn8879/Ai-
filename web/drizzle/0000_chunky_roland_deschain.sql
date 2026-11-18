CREATE TABLE `story_cache` (
	`key` text PRIMARY KEY NOT NULL,
	`visitor` text NOT NULL,
	`path` text NOT NULL,
	`payload` text NOT NULL,
	`updated` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `relay_health` (
	`id` text PRIMARY KEY NOT NULL,
	`updated` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `relay_requests` (
	`id` text PRIMARY KEY NOT NULL,
	`visitor` text NOT NULL,
	`path` text NOT NULL,
	`method` text NOT NULL,
	`body` text,
	`status` text DEFAULT 'pending' NOT NULL,
	`response` text,
	`http_status` integer,
	`created` integer NOT NULL,
	`expires` integer NOT NULL
);
--> statement-breakpoint
CREATE INDEX `relay_status` ON `relay_requests` (`status`,`created`);