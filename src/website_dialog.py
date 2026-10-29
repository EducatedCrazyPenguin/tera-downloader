"""Automatic website handoff. Worker threads never operate Tk or the clipboard."""
import queue
import threading
import tkinter as tk
from tkinter import simpledialog, ttk
import urllib.parse
import webbrowser

from edge_helper import resolve_shares, configure_browser
from terabox import Cancelled, DownloadError, parse_links, share_id
from website_stream import is_website_source

DIRECT_ROUTE = 'VPN available — Direct'
WEBSITE_ROUTE = 'No VPN — Website'


class WebsiteDialog(simpledialog.Dialog):
    def __init__(self, parent, shares, initial=(), *, browser='firefox', profile_dir=None, setup=False):
        self.shares, self.initial = shares, initial
        self.browser, self.profile_dir, self.setup = browser, profile_dir, setup
        self.origins = {}
        self.events = queue.Queue(); self.stop = threading.Event()
        self.worker = None; self.closing = False; self.poll_id = None
        super().__init__(parent, 'Tera — website helper')

    def body(self, parent):
        automatic = self.browser == 'camoufox' and not self.setup
        heading = 'Tera will resolve the share automatically with Camoufox in the background.' if automatic else f'Tera will open its separate {self.browser.capitalize()} profile' + (' for extension setup.' if self.setup else ' and capture the player link automatically.')
        ttk.Label(parent, text=heading, wraplength=620).pack(anchor='w', pady=6)
        detail = 'uBlock is included. If website verification fails, retry or select Firefox / Edge in Settings → Connection.' if automatic else 'Complete human verification if asked. Tera remembers this separate profile between attempts.'
        ttk.Label(parent, text=detail, wraplength=620).pack(anchor='w', pady=6)
        self.error = tk.StringVar(value='Starting the browser helper…')
        ttk.Label(parent, textvariable=self.error, wraplength=620).pack(anchor='w', pady=6)
        self.retry = ttk.Button(parent, text='Retry small browser', command=self.start_helper)
        self.retry.pack(anchor='w', pady=6)
        if self.setup:
            ttk.Label(parent, text='Add uBlock or your preferred extensions in this browser window, then click Done here. Extensions from your everyday browser are not copied.', wraplength=620).pack(anchor='w', pady=8)
            self.poll_id = self.after(100, self.start_helper)
            return self.retry
        fallback = ttk.LabelFrame(parent, text='Manual fallback if needed', padding=10)
        fallback.pack(fill='x', pady=8)
        self.share = tk.StringVar(value=self.shares[0] if self.shares else '')
        if self.shares:
            ttk.Combobox(fallback, textvariable=self.share, values=self.shares, state='readonly', width=75).pack(fill='x')
            self.manual = ttk.Button(fallback, text='Open in normal browser instead', command=self.open_website)
            self.manual.pack(anchor='w', pady=6)
        ttk.Label(fallback, text='Or paste generated player links, one per line:').pack(anchor='w')
        self.links = tk.Text(fallback, height=3, width=78, wrap='word')
        self.links.pack(fill='x', pady=6); self.links.insert('1.0', '\n'.join(self.initial))
        ttk.Label(parent, text='Saves a streaming copy (.ts). Verified segments can resume after exit. Website/network timeouts still require a reachable website.', wraplength=620).pack(anchor='w', pady=6)
        self.poll_id = self.after(100, self.start_helper)
        return self.links

    def buttonbox(self):
        box = ttk.Frame(self)
        self.use = ttk.Button(box, text='Done' if self.setup else 'Use pasted player links', command=self.cancel if self.setup else self.ok)
        self.use.pack(side='left', padx=6)
        self.cancel_button = ttk.Button(box, text='Cancel', command=self.cancel)
        self.cancel_button.pack(side='left', padx=6)
        box.pack(pady=10); self.bind('<Escape>', self.cancel)

    def start_helper(self):
        if self.closing or self.worker and self.worker.is_alive():
            return
        self.stop = threading.Event()
        self.error.set('Starting background resolution…' if self.browser == 'camoufox' and not self.setup else f"Opening Tera's {self.browser.capitalize()} window…")
        for button in (self.retry, None if self.setup else self.use, getattr(self, 'manual', None)):
            if button:
                button.configure(state='disabled')
        # Keep Tk objects out of worker closures and release Tcl variables on the UI thread.
        messages, stop, shares, resolver = self.events, self.stop, tuple(self.shares), resolve_shares
        browser, profile_dir, setup, configure = self.browser, self.profile_dir, self.setup, configure_browser
        def work():
            origins = {}
            try:
                status = lambda text: messages.put(('status', text))
                if setup:
                    configure(browser, profile_dir, stop, status)
                    links = []
                else:
                    links = resolver(shares, stop, status, browser=browser, profile_dir=profile_dir,origins=origins)
                messages.put(('done', (links,origins)))
            except Cancelled:
                messages.put(('cancelled', None))
            except DownloadError as error:
                messages.put(('error', str(error)))
            except Exception:
                messages.put(('error', 'The website helper stopped. Retry or use a generated player link below.'))
        self.worker = threading.Thread(target=work, daemon=True, name='TeraWebsiteHelper')
        self.worker.start(); self.poll_id = self.after(50, self.poll_helper)

    def poll_helper(self):
        self.poll_id = None
        if self.closing:
            if self.worker and self.worker.is_alive():
                self.poll_id = self.after(50, self.poll_helper)
            else:
                super().cancel()
            return
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'status':
                self.error.set(value)
            elif kind == 'done':
                value,self.origins=value
                if self.setup:
                    self.cancel()
                    return
                self.links.delete('1.0', 'end')
                self.links.insert('1.0', '\n'.join(dict.fromkeys([*self.initial, *value])))
                self.ok()
                return
            elif kind == 'error':
                self.error.set(value)
                for button in (self.retry, None if self.setup else self.use, getattr(self, 'manual', None)):
                    if button:
                        button.configure(state='normal')
        if self.worker and self.worker.is_alive():
            self.poll_id = self.after(50, self.poll_helper)

    def open_website(self):
        try:
            link = self.share.get(); share_id(link)
            if not webbrowser.open('https://teradownloader.com/download?' + urllib.parse.urlencode({'l':link})):
                self.error.set('The browser could not be opened. Visit teradownloader.com manually.')
        except (DownloadError, OSError):
            self.error.set('The website could not be opened. Visit teradownloader.com manually.')

    def cancel(self, event=None):
        self.closing = True; self.stop.set()
        if self.worker and self.worker.is_alive():
            self.error.set('Closing the owned browser helper…')
            self.cancel_button.configure(state='disabled')
            if self.poll_id is None:
                self.poll_id = self.after(50, self.poll_helper)
        else:
            super().cancel(event)

    def destroy(self):
        self.stop.set()
        if self.poll_id:
            self.after_cancel(self.poll_id); self.poll_id = None
        super().destroy()
        for name in ('share', 'error'):
            self.__dict__.pop(name, None)

    def validate(self):
        try:
            values = parse_links(self.links.get('1.0', 'end'))
            if not all(is_website_source(value) for value in values):
                raise DownloadError('Paste generated player links here; original shares go in Tera\'s main box.')
            self.result = values
            return True
        except DownloadError as error:
            self.error.set(str(error))
            return False
