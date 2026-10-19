"""Tkinter views for the persistent queue. Worker threads never operate widgets."""
from __future__ import annotations

from pathlib import Path
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk

from app_state import default_data_dir
from firefox_session import SessionError, profiles
from queue_manager import QueueManager, TERMINAL, REVIEW
from terabox import DownloadError, TeraBox, open_firefox, parse_links


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


class TeraApp:
    def __init__(self, root, manager, client_factory=None, available_profiles=None):
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
        notebook = self.notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True)
        self.review_page = ttk.Frame(notebook)
        notebook.add(self.review_page, text='Review')
        queue_page, history_page = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(queue_page, text='Queue')
        notebook.add(history_page, text='History')
        self.review_tree = self._tree(self.review_page, ('chosen', 'name', 'size', 'folder', 'detail'),
                                      ('Download', 'Video', 'Size', 'Destination', 'Review / duplicate check'))
        self.review_tree.column('chosen', width=85, stretch=False)
        self.review_tree.bind('<ButtonRelease-1>', self.toggle_review)
        self.review_tree.bind('<space>', self.toggle_review)
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
        self.history_tree = self._tree(history_page, ('name', 'status', 'finished', 'detail'),
                                       ('Video / share', 'Status', 'Finished', 'Detail'))
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
        for button in (self.start_button, self.pause_button, self.boundary_button, self.skip_button, self.cancel_button):
            button.pack(side='left', padx=(0, 6))
        ttk.Label(frame, text='Closing saves pending jobs. Interrupted files restart from zero in this version.', foreground='#555555').pack(anchor='w', pady=(8, 0))
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

    def send(self, action, **data):
        if not self.closing and self.initialized and not self.manager.closed.is_set():
            self.manager.post(action, **data)

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
            open_firefox(self.profile_options.get(self.source.get()), links[0] if links else '')
        except DownloadError as error:
            self.status.set(str(error).split('\n')[0])

    def check_login(self):
        if self.login_busy:
            return
        profile = self.profile_options.get(self.source.get())
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
        for identifier in tree.selection():
            job = next(j for j in self.snapshot['jobs'] if j['id'] == identifier)
            if job['status'] not in {'pending', 'attention', 'review', 'excluded'}:
                self.status.set('Stop the active file before changing its destination; it must restart from zero.')
                return
            folder = filedialog.askdirectory(parent=self.root, initialdir=job['folder'], title='New destination for selected file')
            if folder:
                self.send('destination', job_id=identifier, folder=folder)
            break

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

    def configure_controls(self):
        snapshot = self.snapshot or {}
        available = self.initialized and not self.closing and not self.manager.closed.is_set()
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
        pending = any(j['status'] in {'pending', 'attention'} for j in snapshot.get('jobs', []))
        self.start_button.configure(text='Resume' if snapshot.get('paused') else 'Start queue')
        enabled(self.start_button, available and not self.login_busy and not snapshot.get('stopping') and (snapshot.get('paused') or not working and pending))
        enabled(self.pause_button, available and bool(working) and not snapshot.get('paused'))
        enabled(self.boundary_button, available and bool(working) and not snapshot.get('paused') and not snapshot.get('pause_after'))
        enabled(self.skip_button, available and (bool(snapshot.get('active')) or any(j['status'] == 'attention' for j in snapshot.get('jobs', []))))
        enabled(self.cancel_button, available and bool(working or discovering))
        enabled(self.download_button, available and not self.login_busy and any(j['status'] == 'review' for j in snapshot.get('jobs', [])))
        enabled(self.review_saved_button, available and not discovering and any(j['status'] == 'unreviewed' for j in snapshot.get('jobs', [])))
        jobs = {j['id']: j for j in snapshot.get('jobs', [])}
        selected = jobs.get(self.selected_queue_job(), {})
        for widget in (self.up_button, self.down_button, self.remove_button):
            enabled(widget, available and selected.get('status') == 'pending')
        enabled(self.remove_button, available and selected.get('status') in {'pending', 'attention'})
        history_selection = [jobs[i] for i in self.history_tree.selection() if i in jobs]
        enabled(self.retry_button, available and any(j['status'] == 'failed' and not j['source_blocked'] for j in history_selection))
        enabled(self.reveal_button, available and any(j['status'] == 'completed' for j in history_selection))
        enabled(self.clear_button, available and not working and any(j['status'] in TERMINAL for j in jobs.values()))

    def render(self):
        if not self.snapshot:
            return
        jobs = self.snapshot['jobs']
        rows = []
        history = []
        review = []
        for job in jobs:
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
                status = 'Needs attention' if job['status'] == 'attention' else job['status'].capitalize()
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
        self.configure_controls()

    def poll(self):
        latest = None
        error = None
        while not self.manager.events.empty():
            kind, data = self.manager.events.get_nowait()
            if kind == 'snapshot':
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
                self.initialized = True
            self.status.set(latest['message'])
            self.render()
        if error:
            self.status.set(error)
            self.configure_controls()
        while not self.ui_events.empty():
            kind, text = self.ui_events.get_nowait()
            if kind == 'login_verified':
                self.send('preferences', changes={'firefox_profile': text})
                continue
            self.login_status.set(text)
            if kind == 'login_done':
                self.login_busy = False
                self.configure_controls()
        if self.closing and self.manager.closed.is_set() and not (self.login_thread and self.login_thread.is_alive()):
            if not self.close_error:
                self.destroy()
                return
            self.status.set('The latest changes could not be saved. Previous saved data was kept. Close again to exit.')
        if self.manager.closed.is_set():
            self.configure_controls()
        self.poll_id = self.root.after(50, self.poll)

    def destroy(self):
        if not self.destroyed:
            self.destroyed = True
            self.root.after_cancel(self.poll_id)
            self.root.destroy()

    def close(self):
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
