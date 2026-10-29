# Tera

<!-- impeccable:product-schema 1 -->

## Platform

windows

Native Windows desktop application using Python/Tkinter. Impeccable's mobile/web
platform vocabulary has no Windows value; do not treat this application as a web
page or impose mobile navigation patterns.

## Users

The owner's personal daily use: downloading TeraBox videos and managing batches
without repeatedly supervising them. Public distribution is outside this redesign.

## Product Purpose

Paste a share link and use one obvious Download now action to download all videos.
Reviewing and selecting individual videos is optional. Quick start is implemented
through the existing validated discovery and queue path; runtime evidence is
recorded in development/todo.md.

## Operating Context

Windows desktop, including small windows and larger text settings. The user wants
a non-technical interface. The primary task must remain usable without opening
settings or understanding queue/checkpoint implementation details.

## Capabilities and Constraints

Keep Tkinter and the existing local queue, history, destinations, Firefox login
selection, conservative recovery, bounded retries and run limits. No dependency
or backend migration is needed for the redesign. X saves the queue and exits;
tray use is explicit. Scheduling works only while Tera stays open.

Read selected Firefox TeraBox cookies only, never other browser data. Direct
supported-domain downloads only. Preserve no-overwrite checks, size verification,
owned-partial cleanup and encrypted source storage. Pause and Cancel remain
available during transfers and verification. A restored queue never starts
network work without an explicit Start.

Real authentication and downloads need separate authorization; UI verification
uses synthetic data and isolated application instances. Never manipulate the
owner's active application or real queue to test the redesign.

## Brand Commitments

The product name is Tera. Plain, familiar language and native controls outrank
decorative presentation. No binding color, theme or typeface preference has been
specified beyond the selected Cinema programme direction: warm white, charcoal,
generous filename typography and restrained red actions.

## Product Principles

- Make the next download action obvious and keep it reachable.
- Give downloads and progress more room than occasional configuration.
- Reveal advanced controls when needed without removing their capabilities.
- Explain holds and failures through a clear action the user can take.
- Keep personal state local and preserve it across updates.

## Evidence on Hand

Current behavior is documented in ../README.md and development/todo.md. A mapped native
probe reproduced hidden download/queue controls at existing window sizes on
22 October 2026; invoking withdrawn widgets had not caught clipping. The existing
offline suite has 146 tests and synthetic runtime harnesses. Live-provider resume
and large transfers remain unverified.

**Evidence: 3/3 for the recorded design and checked synthetic source/runtime scope —
user-selected direction, source, mapped desktop captures and offline checks.
Whole-product evidence remains 2/3: live-provider behavior is unverified; current
packaged and installed verification is recorded separately in development/todo.md.**
