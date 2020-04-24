import dash
import os
import requests
from flask import request
import flask.cli
from threading import Thread
from retrying import retry

from IPython.display import HTML, display


class JupyterDash(dash.Dash):
    _shutdown_route = {}

    def __init__(self, base_url=None, **kwargs):
        super(JupyterDash, self).__init__(**kwargs)

        # Check PLOTLY_DASH_DOMAIN_BASE
        if base_url is None:
            domain_base = os.environ.get('PLOTLY_DASH_DOMAIN_BASE', None)
            if domain_base:
                base_url = 'https://' + domain_base

        self.base_url = base_url

        # Register custom route to shut down server
        self._instance_shutdown_route = '/_shutdown'
        shutdown_route = self._instance_shutdown_route

        @self.server.route(shutdown_route, methods=['GET'])
        def shutdown():
            func = request.environ.get('werkzeug.server.shutdown')
            if func is None:
                raise RuntimeError('Not running with the Werkzeug Server')
            func()
            return 'Server shutting down...'

        self.server.logger.disabled = True

    def run_server(
            self,
            host=os.getenv("HOST", "127.0.0.1"),
            port=os.getenv("PORT", "8050"),
            **kwargs
    ):
        # Terminate any existing server using this port
        self._terminate_server_for_port(host, port)

        # Run superclass run_server is separate thread
        super_run_server = super(JupyterDash, self).run_server

        # Configure urls
        requests_pathname_prefix = self.config.get('requests_pathname_prefix', None)
        if requests_pathname_prefix is not None:
            requests_pathname_prefix = requests_pathname_prefix.format(port=port)
            self.config.update({'requests_pathname_prefix': requests_pathname_prefix})
        else:
            requests_pathname_prefix = '/'

        # Compute base url
        if self.base_url is None:
            base = f'http://{host}:{port}'
        else:
            base = self.base_url

        dashboard_url = "{base}{requests_pathname_prefix}".format(
            base=base, requests_pathname_prefix=requests_pathname_prefix
        )

        # Store new shutdown route
        JupyterDash._shutdown_route[port] = self._instance_shutdown_route

        # Enable supported dev tools by default
        for k in [
            'dev_tools_silence_routes_logging',
            'dev_tools_hot_reload',
            # 'dev_tools_ui',  # Stack traces don't work yet
            'dev_tools_props_check',
            'dev_tools_serve_dev_bundles',
            'dev_tools_prune_errors'
        ]:
            if k not in kwargs:
                kwargs[k] = True

        # Disable debug because it doesn't work in notebook
        kwargs['debug'] = False

        # suppress warning banner printed to standard out
        flask.cli.show_server_banner = lambda *args, **kwargs: None

        @retry(
            stop_max_attempt_number=15,
            wait_exponential_multiplier=100,
            wait_exponential_max=1000
        )
        def run():
            super_run_server(host=host, port=port, **kwargs)

        thread = Thread(target=run)
        thread.setDaemon(True)
        thread.start()

        # Display a hyperlink that can be clicked to open Dashboard
        display(HTML(
            "Dash app running on <a href='{dashboard_url}' "
            "target='_blank'>{dashboard_url}</a>".format(
                dashboard_url=dashboard_url
            )
        ))

    @classmethod
    def _terminate_server_for_port(cls, host, port):
        port = str(port)
        if port in cls._shutdown_route:
            shutdown_route = cls._shutdown_route.pop(port)
            shutdown_url = "http://{host}:{port}{shutdown_route}".format(
                host=host, port=port, shutdown_route=shutdown_route
            )
            try:
                response = requests.get(shutdown_url)
            except Exception as e:
                pass
