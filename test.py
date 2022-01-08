#!/usr/bin/python3
# PYTHON_ARGCOMPLETE_OK

# Referer Modifier: Automatic test
# Copyright (C) 2020-2021 Fiona Klute
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import os
import sys
import unittest
import uuid
from collections import namedtuple
from pathlib import Path
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support.ui import WebDriverWait

# Contains data for testing a link: The page to load initially
# (source), the link to click there (target), and the expected Referer
# header for the second request (referer).
testlink = namedtuple('testlink', ['source', 'target', 'referer'])


class RefModTest(unittest.TestCase):
    quit_browser = True

    @classmethod
    def setUpClass(cls):
        cls.ext_dir = Path(__file__).parent
        with open(cls.ext_dir / 'manifest.json') as fh:
            manifest = json.load(fh)

        cls.addon_path = (cls.ext_dir /
                          f'referer-mod-{manifest["version"]}.zip').resolve()
        addon_id = manifest["browser_specific_settings"]["gecko"]["id"]
        addon_dyn_id = str(uuid.uuid4())
        cls.config_url = f'moz-extension://{addon_dyn_id}/options.html'
        cls.popup_url = f'moz-extension://{addon_dyn_id}/popup.html'
        print(f'Dynamic ID: {addon_dyn_id}')

        cls.options = FirefoxOptions()
        # Pre-seed the dynamic addon ID so we can find the options page
        cls.options.set_preference('extensions.webextensions.uuids',
                                   json.dumps({addon_id: addon_dyn_id}))
        # Use the local test environment, see testserver/
        cls.options.set_preference('network.proxy.type', 1)
        cls.options.set_preference('network.proxy.http', 'localhost')
        cls.options.set_preference('network.proxy.http_port', 8080)
        if not os.environ.get('DISPLAY'):
            cls.options.headless = True

    def setUp(self):
        self.browser = webdriver.Firefox(options=self.options)
        self.browser.install_addon(str(self.addon_path), temporary=True)

    def tearDown(self):
        if self.quit_browser:
            self.browser.quit()

    def click_link(self, target):
        links = self.browser.find_elements(By.TAG_NAME, 'a')
        for link in links:
            if link.get_attribute('href') == target:
                # Found target link, click
                link.click()
                return
        self.fail(f'No link to {target} found!')

    def load_config(self, conffile):
        """Import referer-mod configuration from conffile (Path)"""
        self.browser.get(self.config_url)
        import_file = self.browser.find_element(By.ID, 'import_file')
        import_file.send_keys(str(conffile.resolve()))
        import_button = self.browser.find_element(By.ID, 'import_button')
        import_button.click()

    def toggle_deactivate(self):
        """Open the popup and press the (de)activate button. Returns the state
        after, True for modification enabled.

        """
        self.browser.get(self.popup_url)
        deactivate_button = self.browser.find_element(By.ID, 'deactivate')
        initial = 'off' in deactivate_button.get_attribute("class")
        deactivate_button.click()

        # wait for the change to take effect
        wait = WebDriverWait(self.browser, 10)
        # b is the driver supplied to wait, unused here because the
        # lambda function has access to the current context anyway
        wait.until(lambda b: initial
                   != ('off' in deactivate_button.get_attribute("class")))
        return 'off' not in deactivate_button.get_attribute("class")

    def check_referer(self, link, skip_iframe=False):
        self.browser.get(link.source)
        self.click_link(link.target)
        print(f'Navigating: {link.source} -> {link.target}')
        try:
            http_referer = self.browser.find_element(
                By.XPATH, '//td[text()="Referer"]//following::td')
            print(f'Page shows referer: {http_referer.text}')
            self.assertEqual(link.referer, http_referer.text)
        except NoSuchElementException:
            print('Page shows no Referer.')
            if link.referer is not None:
                raise
        script_referrer = self.browser.find_element(By.ID, 'referrer')
        self.assertEqual(link.referer or '', script_referrer.text)
        reflect_referrer = \
            self.browser.find_element(By.ID, 'referrer-reflect')
        self.assertEqual(link.referer or '', reflect_referrer.text)
        # The iframe manipulation might fail on repeated
        # loads, maybe because the cache speeds up loading.
        if not skip_iframe:
            iframe_referrer = \
                self.browser.find_element(By.ID, 'referrer-iframe')
            self.assertEqual(link.referer or '', iframe_referrer.text)

    def testReferers(self):
        self.load_config(self.ext_dir / 'test_config.json')

        # mapping from next target to click to expected Referer, in order
        tests = [
            testlink('http://web.x.test/page/', 'http://web.x.test/page/',
                     'http://web.x.test/page/'),
            testlink('http://web.x.test/page/', 'http://www.x.test/page/',
                     'http://web.x.test/'),
            testlink('http://www.x.test/page/', 'http://site.y.test/page/',
                     'https://www.example.com/'),
            testlink('http://site.y.test/page/', 'http://www.y.test/page/',
                     None),
        ]

        for link in tests:
            with self.subTest(link=link):
                self.check_referer(link)

    def testDeactivate(self):
        self.load_config(self.ext_dir / 'test_config.json')

        # expected behavior with Referer modification active
        link_active = testlink(
            'http://www.x.test/page/', 'http://site.y.test/page/',
            'https://www.example.com/')
        # expected behavior with Referer modification deactivated
        link_deactivated = testlink(
            'http://www.x.test/page/', 'http://site.y.test/page/',
            'http://www.x.test/')

        self.check_referer(link_active)
        self.assertFalse(self.toggle_deactivate())
        self.check_referer(link_deactivated)
        self.assertTrue(self.toggle_deactivate())
        self.check_referer(link_active, skip_iframe=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='Run referer-mod tests')
    parser.add_argument('--no-quit', action='store_false',
                        dest='quit_browser',
                        help='don\'t stop browser instances after tests')

    # enable bash completion if argcomplete is available
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except ImportError:
        pass

    args, argv = parser.parse_known_args()
    RefModTest.quit_browser = args.quit_browser

    unittest.main(verbosity=2, argv=sys.argv[:1] + argv)
