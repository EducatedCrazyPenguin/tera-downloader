"""Tkinter views for the persistent queue. Worker threads never operate widgets."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import math
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk

from app_state import default_data_dir
from firefox_session import FirefoxProfile, SessionError, profiles
from queue_manager import QueueManager, TERMINAL, REVIEW, HOLDS
from terabox import DownloadError, TeraBox, open_firefox, parse_links
from run_policy import validate_options
from desktop_integration import Desktop, Notifications, available as desktop_available
from app_version import VERSION


def size_text(value):
    for suffix in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or suffix == 'TB':
            return f'{value:.1f} {suffix}'
        value /= 1024


def duration_text(value):
    if value is None:
        return '—'
    seconds = max(0, int(value))
    return f'{seconds // 3600:d}h {(seconds % 3600) // 60:02d}m' if seconds >= 3600 else f'{seconds // 60:d}m {seconds % 60:02d}s'


def transfer_message(snapshot):
    checking = snapshot.get('verification')
    if checking and not any(snapshot.get(key) for key in ('paused', 'stopping', 'closing')):
        return f"Checking saved download: {size_text(checking['done'])} of {size_text(checking['total'])}"
    return snapshot['message']


SORTS = {'Original order': ('', False), 'Name A–Z': ('name', False), 'Name Z–A': ('name', True),
         'Size: smallest first': ('size', False), 'Size: largest first': ('size', True),
         'Newest first': ('finished', True), 'Oldest first': ('finished', False)}


def visible_jobs(jobs, search, sort='', reverse=False):
    def name(job):
        return job.get('output_name') or (job['video']['name'] if job.get('video') else 'Share awaiting discovery')
    result = [j for j in jobs if search.strip().casefold() in name(j).casefold()]
    if sort:
        def key(job):
            if sort == 'name':
                return name(job).casefold()
            return (job.get('video') or {}).get('size', 0) if sort == 'size' else job.get('finished', 0)
        result.sort(key=key, reverse=reverse)
    return result


class TeraApp:
    def __init__(self, root, manager, client_factory=None, available_profiles=None, desktop_factory=None):
        self.root, self.manager = root, manager
        self.client_factory = client_factory or TeraBox
        self.snapshot = None
        self._last_rows = {}
        self.initialized = False
        self.closing = False
        self.destroyed = False
        self.close_error = False
        self.login_busy = False
        self.pending_add = None
        self.login_cancel = threading.Event()
        self.login_thread = None
        self.ui_events = queue.Queue()
        self.desktop_supported = desktop_factory is not None or desktop_available()
        self.desktop = (desktop_factory or Desktop)(self.ui_events)
        self.notifications = Notifications()
        self.pending_notifications = []
        self.tray_pending = False
        self.tray_hidden = False
        self.tray_started = 0
        root.title('Tera — download queue')
        root.geometry('1020x760')
        root.minsize(880, 680)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TButton', padding=6, font=('Segoe UI', 10))
        style.configure('TLabel', font=('Segoe UI', 10))
        style.configure('Treeview', rowheight=26, font=('Segoe UI', 10))
        frame = ttk.Frame(root, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Tera', font=('Segoe UI', 24, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Direct downloads · Local queue and history · Firefox login stays in Firefox').pack(anchor='w', pady=(2, 10))
        source_row = ttk.Frame(frame)
        source_row.pack(fill='x')
        self.source = tk.StringVar(value='No login')
        self.profile_options = {'No login': None}
        try:
            available = profiles() if available_profiles is None else available_profiles
        except SessionError:
            available = []
        for profile in available:
            self.profile_options[f'Firefox: {profile.name} ({profile.path.name})'] = profile
        self.source_box = ttk.Combobox(source_row, textvariable=self.source, values=list(self.profile_options), state='readonly', width=45)
        self.source_box.pack(side='left', fill='x', expand=True)
        self.source_box.bind('<<ComboboxSelected>>', self.source_changed)
        self.login_button = ttk.Button(source_row, text='Login in Firefox', command=self.launch_firefox)
        self.login_button.pack(side='left', padx=6)
        self.check_button = ttk.Button(source_row, text='Check login', command=self.check_login)
        self.check_button.pack(side='left')
        self.disconnect_button = ttk.Button(source_row, text='Disconnect', command=self.disconnect)
        self.disconnect_button.pack(side='left', padx=(6, 0))
        self.login_status = tk.StringVar(value='Opening saved queue…')
        ttk.Label(frame, textvariable=self.login_status, wraplength=950).pack(anchor='w', pady=(4, 8))
        ttk.Label(frame, text='Paste share links, one per line or separated by commas.').pack(anchor='w')
        self.links_box = tk.Text(frame, height=3, wrap='word', font=('Segoe UI', 10))
        self.links_box.pack(fill='x', pady=(4, 6))
        folder_row = ttk.Frame(frame)
        folder_row.pack(fill='x')
        self.destination = tk.StringVar(value=str(Path(__file__).parent / 'downloads'))
        self.destination_entry = ttk.Entry(folder_row, textvariable=self.destination)
        self.destination_entry.pack(side='left', fill='x', expand=True)
        self.browse_button = ttk.Button(folder_row, text='Save to…', command=self.browse)
        self.browse_button.pack(side='left', padx=6)
        self.add_button = ttk.Button(folder_row, text='Review links', command=self.add_links)
        self.add_button.pack(side='left')
        self.per_share = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Use a separate folder for each share', variable=self.per_share).pack(anchor='w')
        favorite_row = ttk.Frame(frame)
        favorite_row.pack(fill='x', pady=(5, 9))
        ttk.Label(favorite_row, text='Favorite folders').pack(side='left')
        self.favorite = tk.StringVar()
        self.favorite_box = ttk.Combobox(favorite_row, textvariable=self.favorite, state='readonly', width=30)
        self.favorite_box.pack(side='left', padx=6)
        self.favorite_box.bind('<<ComboboxSelected>>', self.choose_favorite)
        self.favorite_button = ttk.Button(favorite_row, text='Save favorite…', command=self.save_favorite)
        self.favorite_button.pack(side='left')
        self.forget_favorite_button = ttk.Button(favorite_row, text='Remove favorite', command=self.remove_favorite)
        self.forget_favorite_button.pack(side='left', padx=6)
        desktop_row = ttk.Frame(frame)
        desktop_row.pack(fill='x', pady=(0, 6))
        self.tray_button = ttk.Button(desktop_row, text='Minimize to tray', command=self.minimize_to_tray)
        self.tray_button.pack(side='left')
        self.notify_enabled = tk.BooleanVar(value=False)
        self.notify_check = ttk.Checkbutton(desktop_row, text='Notify on completion or action needed', variable=self.notify_enabled,
                                           command=self.change_notifications)
        self.notify_check.pack(side='left', padx=8)
        self.desktop_status = tk.StringVar(value='X saves and exits.' if self.desktop_supported else 'Tray unavailable — optional desktop packages needed.')
        ttk.Label(desktop_row, textvariable=self.desktop_status).pack(side='left')
        notebook = self.notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True)
        self.review_page = ttk.Frame(notebook)
        notebook.add(self.review_page, text='Review')
        queue_page, history_page = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(queue_page, text='Queue')
        notebook.add(history_page, text='History')
        self.limits_page = ttk.Frame(notebook, padding=10)
        notebook.add(self.limits_page, text='Run limits')
        self.timezone_text = tk.StringVar(value='Windows local time')
        ttk.Label(self.limits_page, textvariable=self.timezone_text).grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 8))
        self.limit_speed = tk.StringVar(value='0')
        self.limit_minutes = tk.StringVar(value='0')
        self.limit_bytes = tk.StringVar(value='0')
        self.window_start = tk.StringVar(value='00:00')
        self.window_end = tk.StringVar(value='00:00')
        self.window_enabled = tk.BooleanVar(value=False)
        self.limit_entries = []
        for row, column, label, variable in ((1, 0, 'Speed (KiB/s)', self.limit_speed), (1, 2, 'Run for (minutes)', self.limit_minutes),
                                              (2, 0, 'Run budget (MiB)', self.limit_bytes), (3, 0, 'Window start (HH:MM)', self.window_start),
                                              (3, 2, 'Window end (HH:MM)', self.window_end)):
            ttk.Label(self.limits_page, text=label).grid(row=row, column=column, sticky='w', padx=(0, 6), pady=4)
            entry = ttk.Entry(self.limits_page, textvariable=variable, width=13)
            entry.grid(row=row, column=column + 1, sticky='w', padx=(0, 18))
            self.limit_entries.append(entry)
        self.window_check = ttk.Checkbutton(self.limits_page, text='Enable daily window (overnight supported)', variable=self.window_enabled)
        self.window_check.grid(row=2, column=2, columnspan=2, sticky='w')
        self.apply_limits_button = ttk.Button(self.limits_page, text='Apply limits', command=self.apply_limits)
        self.apply_limits_button.grid(row=4, column=0, sticky='w', pady=8)
        ttk.Label(self.limits_page, text='Zero means unlimited. Limits finish the current file and can overrun by its remaining bytes/time.\nThe run clock includes pauses, window waits and exit time. Only schedule holds auto-resume.', wraplength=720).grid(row=4, column=1, columnspan=3, sticky='w')
        self.run_summary = tk.StringVar(value='No run started')
        ttk.Label(self.limits_page, textvariable=self.run_summary, wraplength=920).grid(row=5, column=0, columnspan=4, sticky='w')
        self.review_search, self.review_sort = self.search_controls(self.review_page, 'Review', list(SORTS)[:5])
        self.review_tree = self._tree(self.review_page, ('chosen', 'name', 'size', 'folder', 'detail'),
                                      ('Download', 'Video', 'Size', 'Destination', 'Review / duplicate check'))
        self.review_tree.column('chosen', width=85, stretch=False)
        self.review_tree.bind('<ButtonRelease-1>', self.toggle_review)
        self.review_tree.bind('<space>', self.toggle_review)
        selection_row = ttk.Frame(self.review_page)
        selection_row.pack(fill='x')
        ttk.Button(selection_row, text='Select visible', command=lambda: self.choose_visible(True)).pack(side='left')
        ttk.Button(selection_row, text='Deselect visible', command=lambda: self.choose_visible(False)).pack(side='left', padx=6)
        self.review_summary = tk.StringVar(value='Review links to choose videos before downloading.')
        ttk.Label(self.review_page, textvariable=self.review_summary, wraplength=930).pack(anchor='w', pady=4)
        review_actions = ttk.Frame(self.review_page)
        review_actions.pack(fill='x')
        self.download_button = ttk.Button(review_actions, text='Download selected', command=self.download_selected)
        self.download_button.pack(side='left')
        self.review_saved_button = ttk.Button(review_actions, text='Review saved shares', command=lambda: self.send('review_saved'))
        self.review_saved_button.pack(side='left', padx=6)
        ttk.Button(review_actions, text='Change folder…', command=lambda: self.change_destination(self.review_tree)).pack(side='left')
        ttk.Button(review_actions, text='Rename…', command=lambda: self.rename_selected(self.review_tree)).pack(side='left', padx=6)
        ttk.Button(review_actions, text='Remove', command=lambda: self.remove_selected(self.review_tree)).pack(side='left')
        self.queue_tree = self._tree(queue_page, ('name', 'status', 'size', 'progress', 'source', 'folder'),
                                     ('Video / share', 'Status', 'Size', 'Progress', 'Login source', 'Destination'))
        edit = ttk.Frame(queue_page)
        edit.pack(fill='x', pady=5)
        self.up_button = ttk.Button(edit, text='Move up', command=lambda: self.move(-1))
        self.down_button = ttk.Button(edit, text='Move down', command=lambda: self.move(1))
        self.remove_button = ttk.Button(edit, text='Remove pending', command=self.remove_pending)
        for button in (self.up_button, self.down_button, self.remove_button):
            button.pack(side='left', padx=(0, 6))
        ttk.Button(edit, text='Change folder…', command=lambda: self.change_destination(self.queue_tree)).pack(side='left')
        ttk.Button(edit, text='Rename…', command=lambda: self.rename_selected(self.queue_tree)).pack(side='left', padx=6)
        self.restart_button = ttk.Button(edit, text='Restart from zero', command=self.restart_selected)
        self.restart_button.pack(side='left')
        self.retry_queue_button = ttk.Button(edit, text='Retry selected', command=lambda: self.send('retry', job_ids=list(self.queue_tree.selection())))
        self.retry_queue_button.pack(side='left', padx=6)
        self.history_filter = tk.StringVar(value='All')
        filter_row = ttk.Frame(history_page)
        filter_row.pack(fill='x', pady=5)
        filter_box = ttk.Combobox(filter_row, textvariable=self.history_filter, state='readonly', values=['All', 'Completed', 'Failed', 'Skipped', 'Cancelled'], width=15)
        filter_box.pack(side='left')
        filter_box.bind('<<ComboboxSelected>>', lambda event: self.render())
        self.retry_button = ttk.Button(filter_row, text='Retry selected failures', command=self.retry_failed)
        self.retry_button.pack(side='left', padx=6)
        self.reveal_button = ttk.Button(filter_row, text='Reveal folder', command=self.reveal_folder)
        self.reveal_button.pack(side='left')
        self.clear_button = ttk.Button(filter_row, text='Clear history', command=lambda: self.send('clear_history'))
        self.clear_button.pack(side='left', padx=6)
        self.restart_history_button = ttk.Button(filter_row, text='Restart from zero', command=lambda: self.restart_selected(self.history_tree))
        self.restart_history_button.pack(side='left')
        self.history_search, self.history_sort = self.search_controls(history_page, 'History', list(SORTS)[:3] + list(SORTS)[5:])
        self.history_tree = self._tree(history_page, ('name', 'status', 'finished', 'detail'),
                                       ('Video / share', 'Status', 'Finished', 'Detail'))
        help_page = ttk.Frame(notebook, padding=12)
        notebook.add(help_page, text='Help / About')
        ttk.Label(help_page, text=f'Tera {VERSION}', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(help_page, text=(
            'Select your Firefox profile, sign into TeraBox there, then use Check login.\n'
            'Review links and choose videos before downloading.\n\n'
            'Checking saved download verifies your existing bytes before continuing.\n'
            'Login required: refresh the saved Firefox login, then Retry selected.\n'
            'Storage needs attention: check the destination, free space and conflicting files.\n'
            'Restart required: continuing could not be verified; Restart from zero discards that partial.\n'
            'Retry waits are bounded. Pause, Cancel and X remain available.\n'
            'X saves the queue and exits. Reopening waits for Start.\n\n'
            'Diagnostics contain version, fixed event codes, times and counts only.\n'
            'They exclude filenames, folders, links, credentials and raw error text.\n'
            'Nothing is uploaded. Live TeraBox resume support remains unverified.'),
            wraplength=780, justify='left').pack(anchor='w', pady=12)
        self.diagnostics_button = ttk.Button(help_page, text='Save diagnostics…', command=self.save_diagnostics)
        self.diagnostics_button.pack(anchor='w')
        self.queue_tree.bind('<<TreeviewSelect>>', lambda event: self.configure_controls())
        self.history_tree.bind('<<TreeviewSelect>>', lambda event: self.configure_controls())
        self.status = tk.StringVar(value='Opening saved queue…')
        ttk.Label(frame, textvariable=self.status, wraplength=950).pack(anchor='w', pady=(8, 4))
        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.pack(fill='x')
        self.dashboard = tk.StringVar(value='No transfer running')
        ttk.Label(frame, textvariable=self.dashboard, wraplength=950).pack(anchor='w', pady=5)
        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        self.start_button = ttk.Button(actions, text='Start queue', command=lambda: self.send('start'))
        self.pause_button = ttk.Button(actions, text='Pause now', command=self.pause_now)
        self.boundary_button = ttk.Button(actions, text='Finish current, then pause', command=lambda: self.send('pause_after'))
        self.skip_button = ttk.Button(actions, text='Skip', command=self.skip_selected)
        self.cancel_button = ttk.Button(actions, text='Cancel queue', command=lambda: self.send('cancel'))
        self.new_run_button = ttk.Button(actions, text='Start new run', command=lambda: self.send('start', new_run=True))
        for button in (self.start_button, self.pause_button, self.boundary_button, self.skip_button, self.cancel_button, self.new_run_button):
            button.pack(side='left', padx=(0, 6))
        ttk.Label(frame, text='Closing saves verified partial bytes. Continuation requires server validation; live TeraBox resume is unverified.', foreground='#555555', wraplength=950).pack(anchor='w', pady=(8, 0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.configure_controls()
        self.poll_id = root.after(50, self.poll)

    def _tree(self, parent, columns, headings):
        area = ttk.Frame(parent)
        area.pack(fill='both', expand=True)
        tree = ttk.Treeview(area, columns=columns, show='headings', height=6)
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, width=110 if column not in ('name', 'detail', 'folder') else 210, minwidth=65)
        vertical = ttk.Scrollbar(area, orient='vertical', command=tree.yview)
        horizontal = ttk.Scrollbar(area, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom', fill='x')
        vertical.pack(side='right', fill='y')
        tree.pack(fill='both', expand=True)
        return tree

    def search_controls(self, parent, label, sorts):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=label + ' filename').pack(side='left')
        search, sort = tk.StringVar(), tk.StringVar(value='Original order')
        ttk.Entry(row, textvariable=search).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Label(row, text='Sort').pack(side='left')
        ttk.Combobox(row, textvariable=sort, values=sorts, state='readonly', width=22).pack(side='left', padx=6)
        search.trace_add('write', lambda *args: self.render())
        sort.trace_add('write', lambda *args: self.render())
        return search, sort

    def save_diagnostics(self):
        destination = filedialog.asksaveasfilename(parent=self.root, title='Save private diagnostics',
                                                  initialfile='Tera-diagnostics.json', defaultextension='.json',
                                                  filetypes=[('Diagnostics', '*.json')])
        if destination:
            self.send('diagnostics', destination=destination)

    def choose_visible(self, selected):
        if self.snapshot:
            visible = set(self.review_tree.get_children())
            self.send('review_choices', job_ids=[j['id'] for j in self.snapshot['jobs']
                                                if j['id'] in visible and j['status'] in {'review', 'excluded'}], selected=selected)

    def send(self, action, **data):
        if not self.closing and self.initialized and not self.manager.closed.is_set():
            self.manager.post(action, **data)

    def minimize_to_tray(self):
        if not self.desktop_supported or self.closing:
            return
        self.tray_pending = True
        self.ensure_desktop()
        if self.desktop.ready.is_set():
            self.hide_to_tray()

    def ensure_desktop(self):
        if not self.closing and self.desktop.thread is None:
            self.tray_started = time.monotonic()
            self.desktop.start()

    def hide_to_tray(self):
        if self.tray_pending and self.desktop.ready.is_set() and not self.closing:
            self.root.withdraw()
            self.tray_hidden, self.tray_pending = True, False

    def restore_window(self):
        self.tray_pending = False
        self.tray_hidden = False
        self.root.deiconify()

    def change_notifications(self):
        self.send('preferences', changes={'notifications': self.notify_enabled.get()})

    def desktop_event(self, action):
        if action == 'ready':
            self.hide_to_tray()
        elif action in {'failed', 'notification_failed'}:
            if self.tray_hidden:
                self.restore_window()
            self.tray_pending = False
            self.pending_notifications.clear()
            self.desktop_status.set('Tray failed; keep Tera open. Restart Tera to try again.' if action == 'failed' else 'Windows notification unavailable; see Tera for results.')
            if action == 'failed':
                self.desktop_supported = False
                self.desktop.stop()
            self.configure_controls()
        elif action == 'restore':
            self.restore_window()
        elif action == 'exit':
            if self.tray_hidden:
                self.restore_window()
            self.close()
        elif not self.closing:
            buttons = {'pause': self.pause_button, 'resume': self.start_button, 'cancel': self.cancel_button}
            if action in buttons:
                buttons[action].invoke()

    def source_changed(self, event=None):
        profile = self.profile_options.get(self.source.get())
        if profile:
            self.send('preferences', changes={'firefox_profile': str(profile.path)})
        else:
            self.send('disconnect')
        self.login_status.set('Firefox selected. Check login when ready.' if profile else 'No login selected.')

    def disconnect(self):
        self.source.set('No login')
        self.source_changed()

    def launch_firefox(self):
        try:
            first = self.links_box.get('1.0', 'end').strip()
            links = parse_links(first) if first else []
            open_firefox(self.login_profile(), links[0] if links else '')
        except DownloadError as error:
            self.status.set(str(error).split('\n')[0])

    def check_login(self):
        if self.login_busy:
            return
        profile = self.login_profile()
        if not profile:
            self.login_status.set('Select your Firefox profile first.')
            return
        self.login_busy = True
        self.login_cancel.clear()
        self.configure_controls()
        def work():
            try:
                client = self.client_factory(self.login_cancel, lambda text: self.ui_events.put(('login', text)), profile)
                client.verify_login()
                self.ui_events.put(('login_verified', str(profile.path)))
                text = 'Firefox login verified.'
            except DownloadError as error:
                text = str(error).split('\n')[0]
            except Exception:
                text = 'The login could not be checked. Retry when your connection is ready.'
            self.ui_events.put(('login_done', text))
        self.login_thread = threading.Thread(target=work, name='Tera login', daemon=True)
        self.login_thread.start()

    def login_profile(self):
        selected = self.selected_queue_job()
        job = next((j for j in (self.snapshot or {}).get('jobs', []) if j['id'] == selected and j['status'] == 'login'), None)
        if job:
            reference = job['profile']
            return FirefoxProfile(reference['name'], Path(reference['path'])) if reference else None
        return self.profile_options.get(self.source.get())

    def browse(self):
        chosen = filedialog.askdirectory(parent=self.root, title='Save videos to', initialdir=self.destination.get())
        if chosen:
            self.destination.set(chosen)
            self.send('preferences', changes={'last_destination': chosen})

    def add_links(self):
        if self.pending_add is not None or not self.initialized or self.closing:
            return
        try:
            text = self.links_box.get('1.0', 'end').strip()
            links = parse_links(text)
            if not self.destination.get().strip():
                raise DownloadError('Choose a destination folder first.')
            self.send('review', links=links, folder=self.destination.get().strip(), profile=self.profile_options.get(self.source.get()), per_share=self.per_share.get())
            self.pending_add = text
            self.notebook.select(self.review_page)
            self.configure_controls()
        except DownloadError as error:
            self.status.set(str(error).split('\n')[0])

    def save_favorite(self):
        folder = self.destination.get().strip()
        if not folder:
            self.status.set('Choose a destination folder first.')
            return
        name = simpledialog.askstring('Favorite folder', 'Name this destination:', parent=self.root,
                                      initialvalue=Path(folder).name or 'Downloads')
        if name and name.strip():
            favorites = [f for f in self.snapshot['preferences'].get('favorites', []) if f['name'].casefold() != name.strip().casefold()]
            favorites.append({'name': name.strip(), 'path': str(Path(folder).resolve())})
            self.send('preferences', changes={'favorites': favorites})
            self.favorite.set(name.strip())

    def choose_favorite(self, event=None):
        for favorite in self.snapshot['preferences'].get('favorites', []):
            if favorite['name'] == self.favorite.get():
                self.destination.set(favorite['path'])
                self.send('preferences', changes={'last_destination': favorite['path']})
                break

    def remove_favorite(self):
        favorites = [f for f in self.snapshot['preferences'].get('favorites', []) if f['name'] != self.favorite.get()]
        self.send('preferences', changes={'favorites': favorites})
        self.favorite.set('')

    def selected_queue_job(self):
        selection = self.queue_tree.selection()
        return selection[0] if selection else None

    def toggle_review(self, event):
        if event.keysym == 'space':
            selected = self.review_tree.selection()
            identifier = selected[0] if selected else None
        else:
            identifier = self.review_tree.identify_row(event.y) if self.review_tree.identify_column(event.x) == '#1' else None
        if identifier:
            self.send('review_choice', job_id=identifier)
        return 'break' if event.keysym == 'space' else None

    def download_selected(self):
        if self.snapshot:
            self.send('select', job_ids=[j['id'] for j in self.snapshot['jobs'] if j['status'] == 'review'])

    def change_destination(self, tree):
        identifiers = list(tree.selection())
        if not identifiers:
            return
        jobs = [j for j in self.snapshot['jobs'] if j['id'] in identifiers]
        if any(j['status'] not in {'pending', 'attention', 'review', 'excluded'} or j['checkpoint'].get('file_id') for j in jobs):
            self.status.set('No folders changed. Stop active files and choose Restart from zero for saved partials first.')
            return
        folder = filedialog.askdirectory(parent=self.root, initialdir=jobs[0]['folder'], title='New destination for all selected files')
        if folder:
            self.send('destinations', job_ids=identifiers, folder=folder)

    def rename_selected(self, tree):
        selection = tree.selection()
        if selection:
            job = next(j for j in self.snapshot['jobs'] if j['id'] == selection[0])
            if job['status'] not in {'pending', 'attention', 'review', 'excluded'} or not job['video']:
                self.status.set('Select a reviewed, pending, or held file to rename.')
                return
            name = simpledialog.askstring('Save with another name', 'File name (include extension):', parent=self.root,
                                          initialvalue=job['output_name'] or job['video']['name'])
            if name is not None:
                self.send('destination', job_id=job['id'], name=name)

    def remove_selected(self, tree):
        for identifier in tree.selection():
            self.send('remove', job_id=identifier)

    def skip_selected(self):
        self.send('skip', job_id=self.selected_queue_job())

    def restart_selected(self, tree=None):
        selection = (tree or self.queue_tree).selection()
        if selection:
            self.send('restart', job_id=selection[0])

    def move(self, direction):
        identifier = self.selected_queue_job()
        if identifier:
            self.send('move', job_id=identifier, direction=direction)

    def remove_pending(self):
        identifier = self.selected_queue_job()
        if identifier:
            self.send('remove', job_id=identifier)

    def retry_failed(self):
        self.send('retry', job_ids=list(self.history_tree.selection()))

    def reveal_folder(self):
        selection = self.history_tree.selection()
        if not selection or not self.snapshot:
            return
        job = next((j for j in self.snapshot['jobs'] if j['id'] == selection[0]), None)
        if job and job['status'] == 'completed' and job['path']:
            folder = Path(job['path']).parent
            try:
                if not folder.is_dir():
                    raise OSError('Folder missing')
                os.startfile(str(folder))
            except OSError:
                self.status.set('The saved destination is no longer available.')

    def pause_now(self):
        self.send('pause')
        self.status.set('Pausing… waiting for the current network request.')

    def apply_limits(self):
        try:
            speed, budget = float(self.limit_speed.get()), float(self.limit_bytes.get())
            if not all(math.isfinite(value) and value >= 0 for value in (speed, budget)):
                raise ValueError('Speed and byte limits must be non-negative finite numbers.')
            options = validate_options({'speed_bps': max(1, int(speed * 1024)) if speed else 0,
                                        'deadline_minutes': int(self.limit_minutes.get()),
                                        'byte_budget': max(1, int(budget * 1024 * 1024)) if budget else 0,
                                        'schedule_enabled': self.window_enabled.get(),
                                        'start': self.window_start.get().strip(), 'end': self.window_end.get().strip()})
            self.send('configure_run', options=options)
        except (ValueError, OverflowError) as error:
            self.status.set(str(error) if str(error) else 'Enter valid limits and HH:MM window times.')

    def configure_controls(self):
        snapshot = self.snapshot or {}
        available = self.initialized and not self.closing and not self.manager.closed.is_set()
        self.tray_button.configure(state='normal' if available and self.desktop_supported and not self.tray_pending else 'disabled')
        self.notify_check.configure(state='normal' if available and self.desktop_supported else 'disabled')
        working = snapshot.get('running') or snapshot.get('active')
        discovering = snapshot.get('review_busy')
        def enabled(widget, value):
            widget.configure(state='normal' if value else 'disabled')
        for widget in (self.add_button, self.favorite_button, self.forget_favorite_button, self.browse_button, self.destination_entry):
            enabled(widget, available)
        enabled(self.add_button, available and self.pending_add is None)
        self.favorite_box.configure(state='readonly' if available else 'disabled')
        self.links_box.configure(state='normal' if available else 'disabled')
        self.source_box.configure(state='readonly' if available and not working and not discovering and not self.login_busy else 'disabled')
        for widget in (self.login_button, self.check_button, self.disconnect_button):
            enabled(widget, available and not working and not discovering and not self.login_busy)
        if snapshot.get('paused') and not snapshot.get('active'):
            for widget in (self.login_button, self.check_button):
                enabled(widget, available and not discovering and not self.login_busy)
        pending = any(j['status'] in {'pending', 'attention'} for j in snapshot.get('jobs', []))
        limit_hold = snapshot.get('policy_hold') in {'bytes', 'deadline', 'recovery'}
        manual = snapshot.get('manual_paused', False)
        self.start_button.configure(text='Resume' if manual else 'Waiting for window' if snapshot.get('policy_hold') == 'schedule' and working else 'Start queue')
        unresolved = any(j['status'] in {'restart', 'login'} for j in snapshot.get('jobs', []))
        enabled(self.start_button, available and not limit_hold and not unresolved and not self.login_busy and not snapshot.get('stopping') and (manual or not working and pending))
        enabled(self.pause_button, available and bool(working) and not manual)
        enabled(self.boundary_button, available and bool(working) and not manual and not snapshot.get('pause_after'))
        enabled(self.new_run_button, available and pending and not unresolved and not snapshot.get('active') and not self.login_busy and not snapshot.get('stopping'))
        for widget in (self.apply_limits_button, self.window_check, *self.limit_entries):
            enabled(widget, available)
        enabled(self.skip_button, available and (bool(snapshot.get('active')) or any(j['status'] in HOLDS | {'retry_wait'} for j in snapshot.get('jobs', []))))
        enabled(self.cancel_button, available and bool(working or discovering))
        enabled(self.download_button, available and not self.login_busy and any(j['status'] == 'review' for j in snapshot.get('jobs', [])))
        enabled(self.review_saved_button, available and not discovering and any(j['status'] == 'unreviewed' for j in snapshot.get('jobs', [])))
        jobs = {j['id']: j for j in snapshot.get('jobs', [])}
        selected = jobs.get(self.selected_queue_job(), {})
        for widget in (self.up_button, self.down_button, self.remove_button):
            enabled(widget, available and selected.get('status') == 'pending')
        enabled(self.remove_button, available and selected.get('status') in {'pending', 'attention'})
        enabled(self.restart_button, available and selected.get('id') != snapshot.get('active') and selected.get('status') in HOLDS | {'pending'} and not selected.get('source_blocked'))
        enabled(self.retry_queue_button, available and selected.get('status') == 'login' and not selected.get('source_blocked'))
        history_selection = [jobs[i] for i in self.history_tree.selection() if i in jobs]
        enabled(self.retry_button, available and any(j['status'] == 'failed' and not j['source_blocked'] for j in history_selection))
        enabled(self.restart_history_button, available and any(j['status'] == 'failed' and not j['source_blocked'] for j in history_selection))
        enabled(self.reveal_button, available and any(j['status'] == 'completed' for j in history_selection))
        enabled(self.clear_button, available and not working and any(j['status'] in TERMINAL for j in jobs.values()))

    def render(self):
        if not self.snapshot:
            return
        jobs = self.snapshot['jobs']
        rows = []
        history = []
        review = []
        reviewed = visible_jobs([j for j in jobs if j['status'] in REVIEW], self.review_search.get(), *SORTS[self.review_sort.get()])
        historical = visible_jobs([j for j in jobs if j['status'] in TERMINAL], self.history_search.get(), *SORTS[self.history_sort.get()])
        queued = [j for j in jobs if j['status'] not in REVIEW | TERMINAL]
        for job in reviewed + queued + historical:
            video = job['video']
            name = job['output_name'] or (video['name'] if video else 'Share awaiting discovery')
            if job['status'] in REVIEW:
                review.append((job['id'], ('☑' if job['status'] == 'review' else '☐', name, size_text(video['size']) if video else 'Unknown',
                                           job['folder'], job['error'] or job['status'].capitalize())))
            elif job['status'] in TERMINAL:
                if self.history_filter.get() != 'All' and job['status'] != self.history_filter.get().lower():
                    continue
                finished = time.strftime('%d %b %H:%M', time.localtime(job['finished'])) if job['finished'] else ''
                history.append((job['id'], (name, job['status'].capitalize(), finished, job['error'] or job['path'])))
            else:
                percent = f"{job['received'] / video['size']:.0%}" if video and video['size'] else '—'
                status = {'attention': 'Storage needs attention', 'login': 'Login required', 'restart': 'Restart required',
                          'retry_wait': 'Waiting to retry'}.get(job['status'], job['status'].capitalize())
                if self.snapshot.get('verification') and job['id'] == self.snapshot['active']:
                    status = 'Checking saved download'
                if self.snapshot['paused'] and job['id'] == self.snapshot['active']:
                    status = 'Paused' if self.snapshot['pause_acknowledged'] else 'Pausing…'
                source = job['profile']['name'] if job['profile'] else 'No login'
                rows.append((job['id'], (name, status, size_text(video['size']) if video else 'Unknown', percent, source, job['folder'])))
        for tree, items in ((self.review_tree, review), (self.queue_tree, rows), (self.history_tree, history)):
            if self._last_rows.get(tree) == items:
                continue
            wanted = {identifier for identifier, values in items}
            for identifier in tree.get_children():
                if identifier not in wanted:
                    tree.delete(identifier)
            for index, (identifier, values) in enumerate(items):
                if tree.exists(identifier):
                    tree.item(identifier, values=values)
                    tree.move(identifier, '', index)
                else:
                    tree.insert('', index, iid=identifier, values=values)
            self._last_rows[tree] = items
        chosen = [j for j in jobs if j['status'] == 'review' and j['video']]
        folders = {j['folder'] for j in chosen}
        free = self.snapshot['review_space'].get(next(iter(folders))) if len(folders) == 1 else None
        self.review_summary.set(f"{len(chosen)} selected · {size_text(sum(j['video']['size'] for j in chosen))}" +
                                (f' · Free here: {size_text(free)}' if free is not None else '') +
                                ' · Destinations and space are checked again before downloading.')
        total, received = self.snapshot['total'], self.snapshot['received']
        self.progress['value'] = min(100, received / total * 100) if total else 0
        suffix = ' · more sizes pending discovery' if self.snapshot['unknown'] else ''
        self.dashboard.set(f"{size_text(received)} / {size_text(total)} · {size_text(self.snapshot['speed'])}/s · ETA {duration_text(self.snapshot['eta'])}{suffix}")
        self.favorite_box.configure(values=[f['name'] for f in self.snapshot['preferences'].get('favorites', [])])
        self.timezone_text.set('Windows local time: ' + self.snapshot['timezone'] + ' · Tera must stay running for schedules.')
        run, options = self.snapshot['run_state'], self.snapshot['run_options']
        deadline = datetime.fromtimestamp(run['started'] + options['deadline_minutes'] * 60).astimezone().strftime('%d %b %H:%M %Z') if run['id'] and options['deadline_minutes'] else 'none'
        self.run_summary.set(f"This run received {size_text(run['bytes'])} · Deadline: {deadline} · Hold: {self.snapshot['policy_hold'] or 'none'}")
        self.configure_controls()

    def poll(self):
        latest = None
        error = None
        while not self.manager.events.empty():
            kind, data = self.manager.events.get_nowait()
            if kind == 'snapshot':
                messages = self.notifications.observe(data)
                if self.notify_enabled.get():
                    self.pending_notifications = (self.pending_notifications + messages)[-2:]
                latest = data
            elif kind == 'error':
                error = data
                self.pending_add = None
                if self.closing:
                    self.close_error = True
            elif kind == 'added':
                if self.pending_add is not None and self.links_box.get('1.0', 'end').strip() == self.pending_add:
                    self.links_box.delete('1.0', 'end')
                self.pending_add = None
        if latest:
            self.snapshot = latest
            if not self.initialized:
                preferences = latest['preferences']
                self.destination.set(preferences.get('last_destination', self.destination.get()))
                configured = preferences.get('firefox_profile', '')
                self.source.set(next((label for label, profile in self.profile_options.items()
                                      if profile and str(profile.path) == configured),
                                    'No login' if configured is None else next(iter(list(self.profile_options)[1:]), 'No login')))
                self.login_status.set('Select Firefox to reuse its TeraBox login. Cookies are never saved here.')
                options = latest['run_options']
                self.limit_speed.set(f"{options['speed_bps'] / 1024:.17g}")
                self.limit_bytes.set(f"{options['byte_budget'] / (1024 * 1024):.17g}")
                self.limit_minutes.set(str(options['deadline_minutes']))
                self.window_start.set(options['start'])
                self.window_end.set(options['end'])
                self.window_enabled.set(options['schedule_enabled'])
                self.notify_enabled.set(preferences.get('notifications') is True)
                self.initialized = True
            if self.desktop_supported and self.notify_enabled.get() and latest['preferences'].get('notifications') is True:
                self.ensure_desktop()
            elif not self.notify_enabled.get():
                self.pending_notifications.clear()
            self.status.set(transfer_message(latest))
            self.render()
        if error:
            self.status.set(error)
            self.configure_controls()
        while not self.ui_events.empty():
            kind, text = self.ui_events.get_nowait()
            if kind == 'desktop':
                self.desktop_event(text)
                continue
            if kind == 'login_verified':
                self.send('preferences', changes={'firefox_profile': text})
                continue
            self.login_status.set(text)
            if kind == 'login_done':
                self.login_busy = False
                self.configure_controls()
        if self.desktop.thread and not self.desktop.ready.is_set() and not self.desktop.stopped.is_set() and time.monotonic() - self.tray_started > 5:
            self.desktop_event('failed')
        if self.desktop.ready.is_set() and not self.closing:
            for message in self.pending_notifications:
                self.desktop.notify(message)
            self.pending_notifications.clear()
        if self.closing and self.manager.closed.is_set() and not (self.login_thread and self.login_thread.is_alive()):
            if not self.close_error:
                self.destroy()
                if self.destroyed:
                    return
            else:
                self.status.set('The latest changes could not be saved. Previous saved data was kept. Close again to exit.')
        if self.manager.closed.is_set():
            self.configure_controls()
        self.poll_id = self.root.after(50, self.poll)

    def destroy(self):
        if not self.destroyed:
            self.desktop.stop()
            if not self.desktop.stopped.is_set():
                return
            self.destroyed = True
            self.root.after_cancel(self.poll_id)
            self.root.destroy()

    def close(self):
        self.desktop.stop()
        if self.manager.closed.is_set() and not (self.login_thread and self.login_thread.is_alive()):
            self.destroy()
            return
        self.closing = True
        self.login_cancel.set()
        self.manager.post('close')
        self.status.set('Saving queue and exiting… waiting for the current network request.')
        self.configure_controls()


def gui(data_dir=None):
    root = tk.Tk()
    legacy = Path(__file__).parent / '.tera-settings.json' if data_dir is None else None
    manager = QueueManager(data_dir or default_data_dir(), legacy_settings=legacy)
    TeraApp(root, manager)
    root.mainloop()
