"""Tkinter views for the persistent queue. Worker threads never operate widgets."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import math
import os
import sys
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk

from app_state import default_data_dir, data_override
from windows_runtime import application_mutex, downloads_directory
from firefox_session import FirefoxProfile, SessionError, profiles
from queue_manager import QueueManager, TERMINAL, REVIEW, HOLDS
from terabox import DownloadError, TeraBox, open_firefox, parse_links, validate_proxy
from run_policy import validate_options
from desktop_integration import Desktop, Notifications, available as desktop_available
from app_version import VERSION
from website_stream import is_website_source
from website_dialog import WebsiteDialog, DIRECT_ROUTE, WEBSITE_ROUTE



def queue_visible(jobs, search, state, active):
    query=search.strip().casefold()
    groups={'Pending':{'pending'},'Waiting':{'retry_wait'},'Needs attention':HOLDS}
    return [j for j in jobs if j['status'] not in REVIEW | TERMINAL
            and (state=='All' or state=='Active' and j['id']==active or j['status'] in groups.get(state,set()))
            and query in (j['output_name'] or (j['video']['name'] if j['video'] else 'Share awaiting discovery')).casefold()]

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
        root.title('Tera')
        root.geometry('1020x760')
        root.minsize(880, 680)
        paper, ink, muted, red = '#FAF8F4', '#282624', '#625C56', '#A5262D'
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background=paper, foreground=ink, font=('Segoe UI', 10))
        style.configure('TButton', padding=(10, 6))
        style.configure('Primary.TButton', background=red, foreground='white', font=('Segoe UI', 10, 'bold'))
        style.map('Primary.TButton', background=[('disabled', '#E5DDD7'), ('pressed', '#711B20'), ('active', '#8B2027')],
                  foreground=[('disabled', '#6A625C')])
        style.configure('TEntry', fieldbackground='white', padding=4)
        style.configure('TNotebook', borderwidth=0)
        style.configure('TNotebook.Tab', padding=(14, 8))
        style.map('TNotebook.Tab', background=[('selected', paper)], foreground=[('selected', red)])
        style.configure('Treeview', rowheight=int(20 * float(root.tk.call('tk', 'scaling'))),
                        font=('Segoe UI', 11), fieldbackground='white', background='white', borderwidth=0)
        style.configure('Treeview.Heading', padding=(8, 7), font=('Segoe UI', 10, 'bold'))
        style.map('Treeview', background=[('selected', '#E9D6D3')], foreground=[('selected', ink)])
        style.configure('TProgressbar', background=red, troughcolor='#E7E1D9', thickness=6)
        frame = ttk.Frame(root, padding=(20, 14))
        frame.pack(fill='both', expand=True)
        # Pack fixed controls first so the expanding list yields at small sizes.
        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x', pady=(8, 0))
        header = ttk.Frame(frame)
        header.pack(fill='x', pady=(0, 10))
        ttk.Label(header, text='Tera', font=('Georgia', 22)).pack(side='left')
        ttk.Label(header, text='Route for new links').pack(side='left', padx=(18, 6))
        self.connection_route = tk.StringVar(value=DIRECT_ROUTE)
        self.route_box = ttk.Combobox(header, textvariable=self.connection_route, values=[DIRECT_ROUTE, WEBSITE_ROUTE], state='readonly', width=25)
        self.route_box.pack(side='left')
        self.route_box.bind('<<ComboboxSelected>>', self.route_changed)
        self.settings_button = ttk.Button(header, text='Settings', command=lambda: self.notebook.select(self.settings_page))
        self.settings_button.pack(side='right')
        ttk.Button(header, text='Add links', command=lambda: self.notebook.select(self.queue_page)).pack(side='right', padx=8)
        notebook = self.notebook = ttk.Notebook(frame)
        notebook.pack(fill='both', expand=True)
        self.queue_page = queue_page = ttk.Frame(notebook, padding=(0, 8))
        self.review_page = ttk.Frame(notebook, padding=(0, 8))
        history_page = ttk.Frame(notebook, padding=(0, 8))
        notebook.add(queue_page, text='Downloads')
        notebook.add(self.review_page, text='Choose videos')
        notebook.add(history_page, text='History')
        self.settings_page = ttk.Frame(notebook, padding=(0, 8))
        notebook.add(self.settings_page, text='Settings')
        self.settings_tabs = ttk.Notebook(self.settings_page)
        self.settings_tabs.pack(fill='both', expand=True)
        general_page = self._settings_page('General')
        login_page = self._settings_page('Firefox login')
        connection_page = self._settings_page('Connection')
        self.connection_page = connection_page
        browser_bar = ttk.Frame(connection_page)
        browser_bar.pack(fill='x', pady=(0, 8))
        ttk.Label(browser_bar, text='Website browser').pack(side='left', padx=(0, 8))
        self.helper_browser = tk.StringVar(value='Firefox')
        self.helper_browser_box = ttk.Combobox(browser_bar, textvariable=self.helper_browser, values=['Camoufox', 'Firefox', 'Edge'], state='readonly', width=10)
        self.helper_browser_box.pack(side='left')
        self.helper_browser_box.bind('<<ComboboxSelected>>', self.browser_changed)
        self.helper_setup_button = ttk.Button(browser_bar, text='Set up browser…', command=self.setup_helper_browser)
        self.helper_setup_button.pack(side='left', padx=8)
        self.helper_hint = ttk.Label(browser_bar, text='Extensions and cookies remembered.')
        self.helper_hint.pack(side='left')
        self.limits_page = self._settings_page('Run limits')
        help_page = self._settings_page('Help / About')
        queue_header=ttk.Frame(queue_page)
        queue_header.pack(fill='x')
        ttk.Label(queue_header,text='Share links').pack(side='left')
        self.queue_filter=tk.StringVar(value='All')
        self.queue_search=tk.StringVar()
        self.queue_filter_box=ttk.Combobox(queue_header,textvariable=self.queue_filter,values=['All','Pending','Active','Waiting','Needs attention'],state='readonly',width=15)
        self.queue_filter_box.pack(side='right')
        self.queue_search_entry=ttk.Entry(queue_header,textvariable=self.queue_search,width=14)
        self.queue_search_entry.pack(side='right',padx=6)
        ttk.Label(queue_header,text='Find in queue').pack(side='right')
        self.queue_search.trace_add('write',lambda *args:self.render())
        self.queue_filter.trace_add('write',lambda *args:self.render())
        links_row = ttk.Frame(queue_page)
        links_row.pack(fill='x', pady=(4, 8))
        links_row.columnconfigure(0, weight=1)
        self.links_box = tk.Text(links_row, height=2, wrap='word', font=('Segoe UI', 10),
                                 background='white', foreground=ink, insertbackground=red,
                                 selectbackground='#E9D6D3', selectforeground=ink, relief='solid', borderwidth=1,
                                 highlightcolor=red, highlightthickness=1, padx=8, pady=5)
        self.links_box.grid(row=0, column=0, rowspan=2, sticky='nsew', padx=(0, 10))
        self.download_button = ttk.Button(links_row, text='Download now', style='Primary.TButton', command=lambda: self.add_links(quick=True))
        self.download_button.grid(row=0, column=1, sticky='ew')
        self.add_button = ttk.Button(links_row, text='Choose videos…', command=self.add_links)
        self.add_button.grid(row=1, column=1, sticky='ew', pady=(4, 0))
        folder_row = ttk.Frame(queue_page)
        folder_row.pack(fill='x', pady=(0, 4))
        ttk.Label(folder_row, text='Save to').pack(side='left', padx=(0, 8))
        default_downloads = downloads_directory()
        self.destination = tk.StringVar(value=str(default_downloads) if default_downloads else '')
        self.destination_entry = ttk.Entry(folder_row, textvariable=self.destination)
        self.destination_entry.pack(side='left', fill='x', expand=True)
        self.browse_button = ttk.Button(folder_row, text='Change…', command=self.browse)
        self.browse_button.pack(side='left', padx=(8, 0))
        self.file_actions_button = ttk.Menubutton(folder_row, text='File actions')
        self.file_actions_button.pack(side='left', padx=(8, 0))
        self.file_actions_menu = tk.Menu(self.file_actions_button, tearoff=False)
        self.file_actions_button.configure(menu=self.file_actions_menu)
        ttk.Label(login_page, text='Use your selected Firefox login', font=('Segoe UI', 12, 'bold')).pack(anchor='w', pady=(0, 12))
        source_row = ttk.Frame(login_page)
        source_row.pack(fill='x')
        source_row.columnconfigure(0, weight=1)
        self.source = tk.StringVar(value='No login')
        self.profile_options = {'No login': None}
        try:
            available = profiles() if available_profiles is None else available_profiles
        except SessionError:
            available = []
        for profile in available:
            self.profile_options[f'Firefox: {profile.name} ({profile.path.name})'] = profile
        self.source_box = ttk.Combobox(source_row, textvariable=self.source, values=list(self.profile_options), state='readonly', width=45)
        self.source_box.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 12))
        self.source_box.bind('<<ComboboxSelected>>', self.source_changed)
        self.login_button = ttk.Button(source_row, text='Login in Firefox', command=self.launch_firefox)
        self.login_button.grid(row=1, column=0, sticky='w')
        self.check_button = ttk.Button(source_row, text='Check login', command=self.check_login)
        self.check_button.grid(row=1, column=1, sticky='w', padx=6)
        self.disconnect_button = ttk.Button(source_row, text='Disconnect', command=self.disconnect)
        self.disconnect_button.grid(row=2, column=0, sticky='w', pady=8)
        self.login_status = tk.StringVar(value='Opening saved queue…')
        ttk.Label(login_page, textvariable=self.login_status, wraplength=600).pack(anchor='w', pady=(4, 8))
        ttk.Label(connection_page, text='Connection for Tera', font=('Segoe UI', 12, 'bold')).pack(anchor='w', pady=(0, 12))
        ttk.Label(connection_page, text='Optional HTTP CONNECT proxy. Leave blank for a direct connection.', wraplength=600).pack(anchor='w')
        ttk.Label(connection_page, text='Address: http://[user:password@]host:port').pack(anchor='w', pady=(12, 4))
        self.proxy_url = tk.StringVar()
        self.proxy_entry = ttk.Entry(connection_page, textvariable=self.proxy_url, show='*', width=65)
        self.proxy_entry.pack(fill='x', pady=(0, 8))
        self.proxy_save_button = ttk.Button(connection_page, text='Save connection', command=self.save_proxy)
        self.proxy_save_button.pack(anchor='w')
        self.connection_status = tk.StringVar(value='Opening saved connection…')
        ttk.Label(connection_page, textvariable=self.connection_status, wraplength=600).pack(anchor='w', pady=8)
        ttk.Label(connection_page, text='Bring a trusted proxy address; Tera does not provide one. Firefox login uses Firefox’s own connection. Proxy credentials are protected with your Windows account.', wraplength=600).pack(anchor='w', pady=8)
        self.per_share = tk.BooleanVar(value=False)
        ttk.Checkbutton(general_page, text='Use a separate folder for each share', variable=self.per_share).pack(anchor='w')
        favorite_row = ttk.Frame(general_page)
        favorite_row.pack(fill='x', pady=(5, 9))
        ttk.Label(general_page, text='Favorite folders').pack(anchor='w', pady=(16, 4))
        self.favorite = tk.StringVar()
        self.favorite_box = ttk.Combobox(favorite_row, textvariable=self.favorite, state='readonly', width=30)
        self.favorite_box.pack(side='left', padx=6)
        self.favorite_box.bind('<<ComboboxSelected>>', self.choose_favorite)
        self.favorite_button = ttk.Button(favorite_row, text='Save favorite…', command=self.save_favorite)
        self.favorite_button.pack(side='left')
        self.forget_favorite_button = ttk.Button(favorite_row, text='Remove favorite', command=self.remove_favorite)
        self.forget_favorite_button.pack(anchor='w', pady=6)
        desktop_row = ttk.Frame(general_page)
        desktop_row.pack(fill='x', pady=(0, 6))
        self.tray_button = ttk.Button(desktop_row, text='Minimize to tray', command=self.minimize_to_tray)
        self.tray_button.pack(anchor='w', pady=(12, 0))
        self.notify_enabled = tk.BooleanVar(value=False)
        self.notify_check = ttk.Checkbutton(desktop_row, text='Notify on completion or action needed', variable=self.notify_enabled,
                                           command=self.change_notifications)
        self.notify_check.pack(anchor='w', pady=10)
        self.desktop_status = tk.StringVar(value='X saves and exits.' if self.desktop_supported else 'Tray unavailable — optional desktop packages needed.')
        ttk.Label(desktop_row, textvariable=self.desktop_status, wraplength=600).pack(anchor='w')
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
        self.selected_button = ttk.Button(review_actions, text='Download selected', style='Primary.TButton', command=self.download_selected)
        self.selected_button.pack(side='left', padx=(0, 6))
        self.review_saved_button = ttk.Button(review_actions, text='Review saved', command=lambda: self.send('review_saved'))
        self.review_saved_button.pack(side='left', padx=6)
        ttk.Button(review_actions, text='Change folder…', command=lambda: self.change_destination(self.review_tree)).pack(side='left')
        ttk.Button(review_actions, text='Rename…', command=lambda: self.rename_selected(self.review_tree)).pack(side='left', padx=6)
        ttk.Button(review_actions, text='Remove', command=lambda: self.remove_selected(self.review_tree)).pack(side='left')
        self.queue_tree = self._tree(queue_page, ('name', 'status', 'size', 'progress', 'source', 'folder'),
                                     ('Video / share', 'Status', 'Size', 'Progress', 'Login source', 'Destination'))
        edit = ttk.Frame(queue_page)
        self.up_button = ttk.Button(edit, text='Move up', command=lambda: self.move(-1))
        self.down_button = ttk.Button(edit, text='Move down', command=lambda: self.move(1))
        self.next_button = ttk.Button(edit,text='Move next',command=lambda:self.send('move_next',job_ids=list(self.queue_tree.selection())))
        self.remove_button = ttk.Button(edit, text='Remove pending', command=self.remove_pending)
        for button in (self.up_button, self.down_button, self.remove_button):
            button.pack(side='left', padx=(0, 6))
        ttk.Button(edit, text='Change folder…', command=lambda: self.change_destination(self.queue_tree)).pack(side='left')
        ttk.Button(edit, text='Rename…', command=lambda: self.rename_selected(self.queue_tree)).pack(side='left', padx=6)
        recovery_actions = ttk.Frame(queue_page)
        self.restart_button = ttk.Button(recovery_actions, text='Restart from zero', command=self.restart_selected)
        self.restart_button.pack(side='left')
        self.retry_queue_button = ttk.Button(recovery_actions, text='Retry selected', command=lambda: self.send('retry', job_ids=list(self.queue_tree.selection())))
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
        history_recovery = ttk.Frame(history_page)
        history_recovery.pack(fill='x')
        self.restart_history_button = ttk.Button(history_recovery, text='Restart from zero', command=lambda: self.restart_selected(self.history_tree))
        self.restart_history_button.pack(side='left', pady=4)
        self.history_search, self.history_sort = self.search_controls(history_page, 'History', list(SORTS)[:3] + list(SORTS)[5:])
        self.history_tree = self._tree(history_page, ('name', 'status', 'finished', 'detail'),
                                       ('Video / share', 'Status', 'Finished', 'Detail'))
        for tree in (self.review_tree, self.queue_tree, self.history_tree):
            tree.master.pack_forget()
            tree.master.pack(fill='both', expand=True)
        self.empty_queue = ttk.Label(queue_page, text='Your downloads will appear here. Paste a share link above, then Download now.', wraplength=700, foreground=muted)
        self.empty_queue.pack(anchor='w', pady=8)
        self.queue_tree.master.pack_forget()
        self.queue_tree.master.pack(fill='both', expand=True)
        ttk.Label(help_page, text=f'Tera {VERSION}', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(help_page, text=(
            'Select your Firefox profile, sign into TeraBox there, then use Check login.\n'
            'Paste share links and Download now, or Choose videos to select files.\n\n'
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
        self.dashboard = tk.StringVar(value='No transfer running')
        summary_row = ttk.Frame(footer)
        summary_row.pack(fill='x', pady=(4, 6))
        for column in (0, 1):
            summary_row.columnconfigure(column, weight=1, uniform='summary')
        status_label = ttk.Label(summary_row, textvariable=self.status, wraplength=400)
        status_label.grid(row=0, column=0, sticky='w', padx=(0, 8))
        speed_label = ttk.Label(summary_row, textvariable=self.dashboard, wraplength=400, justify='right')
        speed_label.grid(row=0, column=1, sticky='e')
        def wrap_summary(event):
            for label in (status_label, speed_label):
                label.configure(wraplength=max(200, event.width // 2 - 12))
        summary_row.bind('<Configure>', wrap_summary)
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.pack(fill='x', pady=(0, 6))
        actions = ttk.Frame(footer)
        actions.pack(fill='x')
        self.start_button = ttk.Button(actions, text='Start queue', command=lambda: self.send('start'))
        self.pause_button = ttk.Button(actions, text='Pause now', command=self.pause_now)
        self.boundary_button = ttk.Button(recovery_actions, text='Pause after file', command=lambda: self.send('pause_after'))
        self.skip_button = ttk.Button(recovery_actions, text='Skip', command=self.skip_selected)
        self.cancel_button = ttk.Button(actions, text='Cancel queue', command=lambda: self.send('cancel'))
        self.new_run_button = ttk.Button(self.limits_page, text='Start new run', command=lambda: self.send('start', new_run=True))
        for button in (self.start_button, self.pause_button, self.cancel_button):
            button.pack(side='left', padx=(0, 8))
        self.boundary_button.pack(side='left', padx=6)
        self.skip_button.pack(side='left')
        self.new_run_button.grid(row=6, column=0, sticky='w', pady=10)
        # Reuse each command's existing state check from the native menu.
        self.file_menu_entries = []
        for button in (self.up_button, self.down_button, self.remove_button, self.restart_button,
                       self.retry_queue_button, self.skip_button, self.boundary_button):
            self.file_actions_menu.add_command(label=button['text'], command=button.invoke)
            self.file_menu_entries.append(button)
        self.file_actions_menu.add_separator()
        self.file_actions_menu.add_command(label='Change folder…', command=lambda: self.change_destination(self.queue_tree))
        self.file_actions_menu.add_command(label='Rename…', command=lambda: self.rename_selected(self.queue_tree))
        self.file_actions_menu.add_command(label='Move next',command=self.next_button.invoke)
        self.next_menu_index=self.file_actions_menu.index('end')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.configure_controls()
        self.poll_id = root.after(50, self.poll)

    def _settings_page(self, title):
        page = ttk.Frame(self.settings_tabs)
        self.settings_tabs.add(page, text=title)
        canvas = tk.Canvas(page, background='#FAF8F4', highlightthickness=0, takefocus=True)
        vertical = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
        horizontal = ttk.Scrollbar(page, orient='horizontal', command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom', fill='x')
        vertical.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        body = ttk.Frame(canvas, padding=12)
        window = canvas.create_window(0, 0, window=body, anchor='nw')
        def resize(event=None):
            canvas.itemconfigure(window, width=max(canvas.winfo_width(), body.winfo_reqwidth()))
            canvas.configure(scrollregion=canvas.bbox('all'))
        canvas.bind('<Configure>', resize)
        body.bind('<Configure>', resize)
        canvas.bind('<Next>', lambda event: canvas.yview_scroll(1, 'pages'))
        canvas.bind('<Prior>', lambda event: canvas.yview_scroll(-1, 'pages'))
        self.root.bind('<MouseWheel>', lambda event: canvas.yview_scroll(-int(event.delta / 120), 'units')
                       if str(event.widget).startswith(str(body)) else None, add='+')
        return body

    def _tree(self, parent, columns, headings):
        area = ttk.Frame(parent)
        area.pack(fill='both', expand=True)
        tree = ttk.Treeview(area, columns=columns, show='headings', height=6)
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, width=110 if column not in ('name', 'detail', 'folder') else 210, minwidth=65)
        tree.column('name', width=320, minwidth=200)
        if 'status' in columns:
            tree.column('status', width=190, minwidth=150)
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

    def save_proxy(self):
        if self.login_busy:
            self.status.set('Wait for the login check before changing the connection.')
            return
        try:
            value = validate_proxy(self.proxy_url.get())
            self.send('preferences', changes={'proxy_url': value})
        except DownloadError as error:
            self.status.set(str(error))

    def check_login(self):
        if self.login_busy:
            return
        profile = self.login_profile()
        if not profile:
            self.login_status.set('Select your Firefox profile first.')
            return
        proxy_url = (self.snapshot or {}).get('preferences', {}).get('proxy_url', '')
        proxy = {'proxy_url': proxy_url} if proxy_url else {}
        self.login_busy = True
        self.login_cancel.clear()
        self.configure_controls()
        def work():
            try:
                client = self.client_factory(self.login_cancel, lambda text: self.ui_events.put(('login', text)), profile, **proxy)
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

    def route_changed(self, event=None):
        mode = 'website' if self.connection_route.get() == WEBSITE_ROUTE else 'direct'
        self.send('preferences', changes={'connection_mode': mode})

    def browser_changed(self, event=None):
        self.send('preferences', changes={'website_browser':self.helper_browser.get().casefold()})

    def setup_helper_browser(self):
        if not self.initialized or self.closing:
            return
        browser = self.helper_browser.get().casefold()
        if browser == 'camoufox':
            self.status.set('Camoufox includes uBlock. Choose Firefox or Edge to manage extensions.')
            return
        WebsiteDialog(self.root, [], browser=browser,
                      profile_dir=Path(self.manager.directory) / 'browser-profiles' / browser, setup=True)

    def add_links(self, quick=False):
        if self.pending_add is not None or not self.initialized or self.closing:
            return
        try:
            text = self.links_box.get('1.0', 'end').strip()
            links = parse_links(text)
            if not self.destination.get().strip():
                raise DownloadError('Choose a destination folder first.')
            origins = {}
            website = self.connection_route.get() == WEBSITE_ROUTE
            if website and any(not is_website_source(link) for link in links):
                dialog = WebsiteDialog(self.root, [link for link in links if not is_website_source(link)],
                                       [link for link in links if is_website_source(link)],
                                       browser=self.helper_browser.get().casefold(),
                                       profile_dir=Path(self.manager.directory) / 'browser-profiles' / self.helper_browser.get().casefold())
                if not dialog.result or self.closing:
                    return
                links = dialog.result
                origins = getattr(dialog,'origins',{})
            elif not website and any(is_website_source(link) for link in links):
                raise DownloadError('Choose No VPN — Website above for a generated player link.')
            self.send('download_now' if quick else 'review', links=links, origins=origins, folder=self.destination.get().strip(), profile=None if website else self.profile_options.get(self.source.get()), per_share=self.per_share.get())
            self.pending_add = text
            self.notebook.select(self.queue_page if quick else self.review_page)
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
            self.notebook.select(self.queue_page)

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
        identifiers=list(self.queue_tree.selection())
        if identifiers:self.send('move',job_ids=identifiers,direction=direction)

    def remove_pending(self):
        identifiers=list(self.queue_tree.selection())
        if identifiers:self.send('remove',job_ids=identifiers)

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
        for widget in (self.proxy_entry, self.proxy_save_button):
            enabled(widget, available and not working and not discovering and not self.login_busy)
        self.helper_browser_box.configure(state='readonly' if available else 'disabled')
        camoufox = self.helper_browser.get().casefold() == 'camoufox'
        enabled(self.helper_setup_button, available and not camoufox)
        self.helper_hint.configure(text='uBlock included. Background helper.' if camoufox else 'Extensions and cookies remembered.')
        self.favorite_box.configure(state='readonly' if available else 'disabled')
        self.links_box.configure(state='normal' if available else 'disabled')
        self.route_box.configure(state='readonly' if available and not self.login_busy else 'disabled')
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
        enabled(self.download_button, available and not self.login_busy and self.pending_add is None)
        enabled(self.selected_button, available and not self.login_busy and any(j['status'] == 'review' for j in snapshot.get('jobs', [])))
        enabled(self.review_saved_button, available and not discovering and any(j['status'] == 'unreviewed' for j in snapshot.get('jobs', [])))
        jobs = {j['id']: j for j in snapshot.get('jobs', [])}
        selected = jobs.get(self.selected_queue_job(), {})
        selection=[jobs[i] for i in self.queue_tree.selection() if i in jobs]
        pending=bool(selection) and all(j['status']=='pending' and j['id']!=snapshot.get('active') for j in selection)
        for widget in (self.up_button,self.down_button,self.next_button):enabled(widget,available and pending)
        enabled(self.remove_button,available and bool(selection) and all(j['status'] in {'pending','attention'} and j['id']!=snapshot.get('active') for j in selection))
        self.file_actions_menu.entryconfigure(self.next_menu_index,state='normal' if available and pending else 'disabled')
        enabled(self.restart_button, available and selected.get('id') != snapshot.get('active') and selected.get('status') in HOLDS | {'pending'} and not selected.get('source_blocked'))
        enabled(self.retry_queue_button, available and selected.get('status') == 'login' and not selected.get('source_blocked'))
        history_selection = [jobs[i] for i in self.history_tree.selection() if i in jobs]
        enabled(self.retry_button, available and any(j['status'] == 'failed' and not j['source_blocked'] for j in history_selection))
        enabled(self.restart_history_button, available and any(j['status'] == 'failed' and not j['source_blocked'] for j in history_selection))
        enabled(self.reveal_button, available and any(j['status'] == 'completed' for j in history_selection))
        enabled(self.clear_button, available and not working and any(j['status'] in TERMINAL for j in jobs.values()))
        for index, button in enumerate(self.file_menu_entries):
            self.file_actions_menu.entryconfigure(index, state='disabled' if button.instate(['disabled']) else 'normal')
        for index in (8, 9):
            self.file_actions_menu.entryconfigure(index, state='normal' if available and selected.get('status') in {'pending', 'attention'} else 'disabled')

    def render(self):
        if not self.snapshot:
            return
        jobs = self.snapshot['jobs']
        rows = []
        history = []
        review = []
        reviewed = visible_jobs([j for j in jobs if j['status'] in REVIEW], self.review_search.get(), *SORTS[self.review_sort.get()])
        historical = visible_jobs([j for j in jobs if j['status'] in TERMINAL], self.history_search.get(), *SORTS[self.history_sort.get()])
        queued = queue_visible(jobs,self.queue_search.get(),self.queue_filter.get(),self.snapshot.get('active'))
        filtered=bool(self.queue_search.get().strip()) or self.queue_filter.get()!='All'
        self.empty_queue.configure(text='No queue items match. Clear Find in queue and choose All to show the queue.' if filtered else 'Your downloads will appear here. Paste a share link above, then Download now.')
        if queued:
            self.empty_queue.pack_forget()
        elif not self.empty_queue.winfo_manager():
            self.empty_queue.pack(before=self.queue_tree.master, anchor='w', pady=8)
        for job in reviewed + queued + historical:
            video = job['video']
            name = job['output_name'] or (video['name'] if video else 'Share awaiting discovery')
            if job['status'] in REVIEW:
                review.append((job['id'], ('☑' if job['status'] == 'review' else '☐', name, size_text(video['size']) if video and video['size'] else 'Stream' if video else 'Unknown',
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
                source = 'Website stream' if is_website_source(job['link']) else job['profile']['name'] if job['profile'] else 'No login'
                rows.append((job['id'], (name, status, size_text(video['size']) if video and video['size'] else 'Stream' if video else 'Unknown', percent, source, job['folder'])))
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
        self.configure_controls()
        chosen = [j for j in jobs if j['status'] == 'review' and j['video']]
        folders = {j['folder'] for j in chosen}
        free = self.snapshot['review_space'].get(next(iter(folders))) if len(folders) == 1 else None
        streams = sum(not j['video']['size'] for j in chosen)
        self.review_summary.set(f"{len(chosen)} selected · {size_text(sum(j['video']['size'] for j in chosen))} known" +
                                (f' · {streams} stream size(s) checked during download' if streams else '') +
                                (f' · Free here: {size_text(free)}' if free is not None else '') +
                                ' · Destinations and space are checked again before downloading.')
        total, received = self.snapshot['total'], self.snapshot['received']
        self.progress['value'] = min(100, received / total * 100) if total else 0
        suffix = ' · total size not yet known' if self.snapshot['unknown'] else ''
        amount = size_text(received) if self.snapshot['unknown'] else f'{size_text(received)} / {size_text(total)}'
        self.dashboard.set(f"{amount} · {size_text(self.snapshot['speed'])}/s · ETA {duration_text(self.snapshot['eta'])}{suffix}")
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
                self.proxy_url.set(preferences.get('proxy_url', ''))
                self.connection_route.set(WEBSITE_ROUTE if preferences.get('connection_mode') == 'website' else DIRECT_ROUTE)
                self.helper_browser.set(preferences.get('website_browser', 'firefox').capitalize())
                self.initialized = True
            if self.desktop_supported and self.notify_enabled.get() and latest['preferences'].get('notifications') is True:
                self.ensure_desktop()
            elif not self.notify_enabled.get():
                self.pending_notifications.clear()
            self.connection_status.set('Tera uses the saved proxy for its requests.' if latest['preferences'].get('proxy_url') else 'Direct connection. No app proxy configured.')
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
            for window in self.root.winfo_children():
                if isinstance(window, WebsiteDialog):
                    window.cancel()
                    return
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
    data_dir = data_override(data_dir)
    with application_mutex():
        root = tk.Tk()
        legacy_root = Path(__file__).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]
        legacy = legacy_root / '.tera-settings.json' if data_dir is None else None
        manager = QueueManager(data_dir or default_data_dir(), legacy_settings=legacy)
        TeraApp(root, manager)
        root.mainloop()
