from os import environ
from time import time
from typing import Optional
from platform import system
from logging import DEBUG, Formatter, StreamHandler, getLogger
from asyncio import sleep, get_event_loop
from re import match
from bs4 import BeautifulSoup

from inscriptis import get_text

import zendriver

from .internal.objects import Response, SearchResult, Theme
from .internal.selectors import DeepSeekSelectors
from .internal.exceptions import (MissingCredentials, InvalidCredentials, ServerDown, MissingInitialization, CouldNotFindElement,
                                  InvalidChatID)

class DeepSeek:
    def __init__(
        self,
        token: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None,
        chat_id: Optional[str] = None,
        headless: bool = True,
        verbose: bool = False,
        chrome_args: list = [],
        attempt_cf_bypass: bool = True
    ) -> None:
        """Initializes the DeepSeek object.

        Args
        ---------
        token: Optional[str]
            The token of the user.
        email: Optional[str]
            The email of the user.
        password: Optional[str]
            The password of the user.
        chat_id: str
            The chat id.
        headless: bool
            Whether to run the browser in headless mode.
        verbose: bool
            Whether to log the actions.
        chrome_args: list
            The arguments to pass to the Chrome browser.
        attempt_cf_bypass: bool
            Whether to attempt to bypass the Cloudflare protection.

        Raises
        ---------
        ValueError:
            Either the token or the email and password must be provided.
        """
        if not token and not (email and password):
            raise MissingCredentials("Either the token alone or the email and password both must be provided")

        self._email = email
        self._password = password
        self._token = token
        self._chat_id = chat_id
        self._headless = headless
        self._verbose = verbose
        self._chrome_args = chrome_args
        self._attempt_cf_bypass = attempt_cf_bypass

        self._deepthink_enabled = False
        self._search_enabled = False
        self._initialized = False
        self.selectors = DeepSeekSelectors()

    async def initialize(self) -> None:
        """Initializes the DeepSeek session.

        This method sets up the logger, starts a virtual display if necessary, and launches the browser.
        It also navigates to the DeepSeek chat page and handles the login process using either a token
        or email and password.

        Raises
        ---------
        ValueError:
            PyVirtualDisplay is not installed.
        ValueError:
            Xvfb is not installed.
        """

        # Initilize the logger
        self.logger = getLogger("DeeperSeek")
        self.logger.setLevel(DEBUG)

        if self._verbose:
            handler = StreamHandler()
            handler.setFormatter(Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S"))
            self.logger.addHandler(handler)

        # Start the virtual display if the system is Linux and the DISPLAY environment variable is not set
        if system() == "Linux" and "DISPLAY" not in environ:
            self.logger.debug("Starting virtual display...")
            try:
                from pyvirtualdisplay.display import Display

                self.display = Display()
                self.display.start()
            except ModuleNotFoundError:
                raise ValueError(
                    "Please install PyVirtualDisplay to start a virtual display by running `pip install PyVirtualDisplay`"
                )
            except FileNotFoundError as e:
                if "No such file or directory: 'Xvfb'" in str(e):
                    raise ValueError(
                        "Please install Xvfb to start a virtual display by running `sudo apt install xvfb`"
                    )
                raise e

        # Start the browser
        self.browser = await zendriver.start(
            chrome_args = self._chrome_args,
            headless = self._headless
        )

        self.logger.debug("Navigating to the chat page...")
        await self.browser.get("https://chat.deepseek.com/" if not self._chat_id \
            else f"https://chat.deepseek.com/a/chat/s/{self._chat_id}")

        if self._attempt_cf_bypass:
            try:
                self.logger.debug("Verifying the Cloudflare protection...")
                await self.browser.main_tab.verify_cf()
            except: # It times out if there was no need to verify
                pass
        
        self._initialized = True
        self._is_active = True
        loop = get_event_loop()
        loop.create_task(self._keep_alive())
        
        if self._token:
            await self._login()
        else:
            await self._login_classic()
    
    async def _keep_alive(self) -> None:
        """Keeps the browser alive by refreshing the page periodically."""
        try:
            while self._is_active:
                await sleep(300)  # Sleep for 5 minutes (adjustable)
                if hasattr(self, "browser"):
                    # self.logger.debug("Refreshing the page to keep session alive...")
                    # await self.browser.main_tab.reload()
                    continue
        except Exception as e:
            self.logger.error(f"Keep-alive encountered an error: {e}")

    def __del__(self) -> None:
        """Destructor method to stop the browser and the virtual display."""

        self._is_active = False

    async def _login(self) -> None:
        """Logs in to DeepSeek using a token.

        This method sets the token in the browser's local storage and reloads the page to authenticate.
        If the token is invalid, it falls back to the classic login method. (email and password)

        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        self.logger.debug("Logging in using the token...")
        await self.browser.main_tab.evaluate(
            f"localStorage.setItem('userToken', JSON.stringify({{value: '{self._token}', __version: '0'}}))",
            await_promise = True,
            return_by_value = True
        )
        await self.browser.main_tab.reload()
        
        # Reloading with an invalid token still gives access to the website somehow, but only for a split second
        # So I added a delay to make sure the token is actually invalid
        await sleep(2)
        
        # Check if the token login was successful
        try:
            await self.browser.main_tab.wait_for(self.selectors.interactions.textbox, timeout = 5)
        except:
            self.logger.debug("Token failed, logging in using email and password...")

            if self._email and self._password:
                return await self._login_classic(token_failed = True)
            else:
                raise InvalidCredentials("The token is invalid and no email or password was provided")
    
        self.logger.debug("Token login successful!")
        
    async def _login_classic(self, token_failed: bool = False) -> None:
        """Logs in to DeepSeek using email and password.

        Args
        ---------
            token_failed (bool): Indicates whether the token login attempt failed.
        
        Raises:
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
            InvalidCredentials: If the email or password is incorrect.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        self.logger.debug("Entering the email and password...")
        email_input = await self.browser.main_tab.select(self.selectors.login.email_input)
        await email_input.send_keys(self._email)

        password_input = await self.browser.main_tab.select(self.selectors.login.password_input)
        await password_input.send_keys(self._password)

        if self._attempt_cf_bypass:
            self.logger.debug("Checking the confirm checkbox and logging in...")
            confirm_checkbox = await self.browser.main_tab.select(self.selectors.login.confirm_checkbox)
            await confirm_checkbox.click()

        login_button = await self.browser.main_tab.select(self.selectors.login.login_button)
        await login_button.click()

        try:
            await self.browser.main_tab.wait_for(self.selectors.interactions.textbox, timeout = 5)
        except:
            raise InvalidCredentials("The email or password is incorrect" \
                if not token_failed else "Both token and email/password are incorrect")

        self.logger.debug(f"Logged in successfully using email and password! {'(Token method failed)' if token_failed else ''}")
    
    async def _dev_debug(self) -> None:
        """A method for debugging purposes.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")
    
        while True:
            class_id = input("Enter the class id [e to exit]: ")
            if class_id == "e":
                break

            try:
                element = await self.browser.main_tab.select(f'div[class="{class_id}"]', timeout = 3)
            except:
                print("Invalid class id")
                continue
            
            print("breakpoint below")
            breakpoint()
        
    async def _find_child_by_text(
        self,
        parent: zendriver.Element,
        text: str,
        in_depth: bool = False,
        depth_limit: int = 10
    ) -> Optional[zendriver.Element]:
        """Finds a child element by it's text.

        Args
        ---------
            parent (zendriver.Element): The parent element.
            text (str): The text to find.
            in_depth (bool): Whether to search in depth.
            depth_limit (int): The depth limit to search in.

        Returns
        ---------
            Optional[zendriver.Element]: The child element if found, otherwise None.

        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        if in_depth: # not the best way to do this, but it works
            for child in parent.children:
                if child.text_all.lower() == text.lower():
                    return child
                
                if depth_limit:
                    found = await self._find_child_by_text(child, text, in_depth, depth_limit - 1)
                    if found:
                        return found
        else:
            for child in parent.children:
                if child.text_all.lower() == text.lower():
                    return child
        
        return None

    async def retrieve_token(self) -> Optional[str]:
        """Retrieves the token from the browser's local storage.
        
        Returns
        ---------
            Optional[str]: The token if found, otherwise None.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")
        
        return await self.browser.main_tab.evaluate(
            "JSON.parse(localStorage.getItem('userToken')).value",
            await_promise = True,
            return_by_value = True
        )

    async def send_message(
        self,
        message: str,
        slow_mode: bool = False,
        deepthink: bool = False,
        search: bool = False,
        timeout: int = 60,
        slow_mode_delay: float = 0.25
    ) -> Optional[Response]:
        """Sends a message to the DeepSeek chat.

        Args
        ---------
            message (str): The message to send.
            slow_mode (bool): Whether to send the message character by character with a delay.
            deepthink (bool): Whether to enable deepthink mode.
                - Setting this to True will add 20 seconds to the timeout.
            search (bool): Whether to enable search mode.
                - Setting this to True will add 60 seconds to the timeout.
            timeout (int): The maximum time to wait for a response.
                - Sometimes a response may take longer than expected, so it's recommended to increase the timeout if necessary.
                - Do note that the timeout increases by 20 seconds if deepthink is enabled, and by 60 seconds if search is enabled.
            slow_mode_delay (float): The delay between sending each character in slow mode.

        Returns
        ---------
            Optional[Response]: The generated response from DeepSeek, or None if no response is received within the timeout

        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        timeout += 20 if deepthink else 0
        timeout += 60 if search else 0

        self.logger.debug(f"Finding the textbox and sending the message: {message}")
        textbox = await self.browser.main_tab.select(self.selectors.interactions.textbox)
        if slow_mode:
            for char in message:
                await textbox.send_keys(char)
                await sleep(slow_mode_delay)
        else:
            await textbox.send_keys(message)

        # Find the parent div of both deepthink and search options
        send_options_parent = await self.browser.main_tab.select(self.selectors.interactions.send_options_parent)
        
        if deepthink != self._deepthink_enabled:
            await send_options_parent.children[0].click() # DeepThink (R1)
            self._deepthink_enabled = deepthink
        
        if search != self._search_enabled:
            await send_options_parent.children[1].click() # Search
            self._search_enabled = search

        send_button = await self.browser.main_tab.select(self.selectors.interactions.send_button)
        await send_button.click()

        return await self._get_response(timeout = timeout)

    async def regenerate_response(self, timeout: int = 60) -> Optional[Response]:
        """Regenerates the response from DeepSeek.

        Args
        ---------
            timeout (int): The maximum time to wait for the response.

        Returns
        ---------
            Optional[Response]: The regenerated response from DeepSeek, or None if no response is received within the timeout
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
            ServerDown: If the server is busy and the response is not generated.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        # Find the last response so I can access it's buttons
        toolbar = await self.browser.main_tab.select_all(self.selectors.interactions.response_toolbar)
        await toolbar[-1].children[1].click()

        return await self._get_response(timeout = timeout, regen = True)
    
    def _filter_search_results(
        self,
        search_results_children: list,
    ):
        """Filters the search results and returns a list of SearchResult objects.

        Args
        ---------
            search_results_children (list): The search results children.

        Returns
        ---------
            list: A list of SearchResult objects.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        search_results = []
        for search_result in search_results_children:
            search_results.append(
                SearchResult(
                    image_url = BeautifulSoup(
                        str(search_result.children[0].children[0].children),
                        'html.parser'
                    ).find('img')['src'],
                    website = search_result.children[0].children[1].text_all,
                    date = search_result.children[0].children[2].text_all,
                    index = int(search_result.children[0].children[3].text_all),
                    title = search_result.children[1].text_all,
                    description = search_result.children[2].text_all
                )
            )
        
        return search_results

    async def _get_response(
        self,
        timeout: int = 60,
        regen: bool = False,
    ) -> Optional[Response]:
        """Waits for and retrieves the response from DeepSeek.

        Args
        ---------
            timeout (int): The maximum time to wait for the response.
            regen (bool): Whether the response is a regenerated response.

        Returns
        ---------
            Optional[Response]: The generated response from DeepSeek, or None if no response is received within the timeout.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
            ServerDown: If the server is busy and the response is not generated.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        end_time = time() + timeout

        # Wait till the response starts generating
        # If we don't wait for the response to start re/generating, we might get the previous response
        self.logger.debug("Waiting for the response to start generating..." if not regen \
            else "Waiting for the response to start regenerating...")
        while time() < end_time:
            try:
                _ = await self.browser.main_tab.select(self.selectors.backend.response_generating if not regen \
                    else self.selectors.backend.regen_loading_icon)
            except:
                continue
            else:
                break
        
        if time() >= end_time:
            return None

        # Once the response starts generating, wait till it's generated
        response_generated = None
        self.logger.debug("Waiting for the response to finish generating..." if not regen \
            else "Finding the last response...")
        while time() < end_time:
            try:
                response_generated: zendriver.Element = await self.browser.main_tab.select_all(
                    self.selectors.backend.response_generated)
            except:
                continue

            if response_generated:
                break
        
        if not response_generated:
            return None
        
        if regen:
            # Wait till toolbar appears
            self.logger.debug("Waiting for the response toolbar to appear...")
            while time() < end_time:
                # I need to keep refreshing the response_generated list because the elements change
                try:
                    response_generated: zendriver.Element = await self.browser.main_tab.select_all(
                        self.selectors.backend.response_generated)
                except Exception as e:
                    continue

                # Check if the toolbar is present
                soup = BeautifulSoup(repr(response_generated[-1]), 'html.parser')
                toolbar = soup.find("div", class_ = self.selectors.backend.response_toolbar_b64)
                if not toolbar:
                    continue

                response_generated = await self.browser.main_tab.select_all(self.selectors.backend.response_generated)
                break
            
            if time() >= end_time:
                return None

        self.logger.debug("Extracting the response text...")
        soup = BeautifulSoup(repr(response_generated[-1]), 'html.parser')
        markdown_blocks = soup.find_all("div", class_ = "ds-markdown ds-markdown--block")
        response_text = "\n\n".join(get_text(str(block)).strip() for block in markdown_blocks)

        if response_text.lower() == "the server is busy. please try again later.":
            raise ServerDown("The server is busy. Please try again later.")

        search_results = None
        deepthink_duration = None
        deepthink_content = None

        # 1 and 2 are the deepthink and search options
        for child in response_generated[-1].children[1:3]:
            if match(r"found \d+ results", child.text.lower()) and self._search_enabled:
                self.logger.debug("Extracting the search results...")
                # So this is a search result option, we need to click it and find the search results div
                await child.click()

                search_results = await self.browser.main_tab.select_all(self.selectors.interactions.search_results)
                # First child is "Search Results". Second child is the actual search results
                search_results_children = search_results[-1].children[1].children

                search_results = self._filter_search_results(search_results_children)
            
            if match(r"thought for \d+(\.\d+)? seconds", child.text.lower()) and self._deepthink_enabled:
                self.logger.debug("Extracting the deepthink duration and content...")
                # This is the deepthink option, we can find the duration through splitting the text
                deepthink_duration = int(child.text.split()[2])
                
                # DeepThink content is shown by default, no need to click anything
                deepthink_content = await self.browser.main_tab.select_all(self.selectors.interactions.deepthink_content)
                soup = BeautifulSoup(repr(deepthink_content[-1]), 'html.parser')
                deepthink_content = "\n".join(get_text(str(p)).strip() for p in soup.find_all('p'))

        response = Response(
            text = response_text,
            chat_id = self._chat_id,
            deepthink_duration = deepthink_duration,
            deepthink_content = deepthink_content,
            search_results = search_results
        )
        
        self.logger.debug("Response generated!")
        return response
    
    async def reset_chat(self) -> None:
        """Resets the chat by clicking the reset button.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        reset_chat_button = await self.browser.main_tab.select(self.selectors.interactions.reset_chat_button)
        await reset_chat_button.click()
        self.chat_id = ""
        self.logger.debug("Chat reset!")
    
    async def logout(self) -> None:
        """Logs out of the DeepSeek account.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        self.logger.debug("Logging out...")
        await self.browser.main_tab.evaluate(
            "localStorage.removeItem('userToken')",
            await_promise = True,
            return_by_value = True
        )
        await self.browser.main_tab.reload()
        self.logger.debug("Logged out successfully!")
    
    async def switch_account(
        self,
        token: Optional[str] = None,
        email: Optional[str] = None,
        password: Optional[str] = None
    ) -> None:
        """Switches the account by logging out and logging back in with a new token.

        Args
        ---------
            token (Optional[str]): The new token to use.
            email (Optional[str]): The new email to use.
            password (Optional[str]): The new password to use.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method
            MissingCredentials: If neither the token nor the email and password are provided
            InvalidCredentials: If the token or email and password are incorrect
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        # Check if the token or email and password are provided
        if not token and not (email and password):
            raise MissingCredentials("Either the token alone or the email and password both must be provided")

        self.logger.debug("Switching the account...")

        # Log out of the current account
        await self.logout()

        # Update the credentials
        self._token = token
        self._email = email
        self._password = password

        if self._token:
            await self._login()
        else:
            await self._login_classic()
        
    async def delete_chats(self) -> None:
        """Deletes all the chats in the chat.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
            CouldNotFindElement: If the delete chats button is not found.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        self.logger.debug("Clicking the profile button...")
        profile_button = await self.browser.main_tab.select(self.selectors.interactions.profile_button)
        await profile_button.click()
        
        self.logger.debug("Clicking the profile options dropdown...")
        profile_options_dropdown = await self.browser.main_tab.select(self.selectors.interactions.profile_options_dropdown)
        await profile_options_dropdown.click()

        self.logger.debug("Finding and clicking the delete chats button...")
        delete_chats_button = await self._find_child_by_text(
            parent = profile_options_dropdown,
            text = "Delete all chats",
            in_depth = True
        )
        if not delete_chats_button:
            raise CouldNotFindElement("Could not find the delete chats button")

        await delete_chats_button.click()

        self.logger.debug("Clicking the confirm deletion button...")
        confirm_deletion_button = await self.browser.main_tab.select(self.selectors.interactions.confirm_deletion_button)
        await confirm_deletion_button.click()

        self.logger.debug("chats deleted!")
    
    async def switch_chat(self, chat_id: str) -> None:
        """Switches the chat by navigating to a new chat id.

        Args
        ---------
            chat_id (str): The new chat id to navigate to.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
            InvalidChatID: If the chat id is invalid
            CouldNotFindElement: If the textbox is not found
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        self.logger.debug(f"Switching the chat to: {chat_id}")
        await self.browser.main_tab.get(f"https://chat.deepseek.com/a/chat/s/{chat_id}")

        # Wait till text box appears
        self.logger.debug("Waiting for the textbox to appear...")
        try:
            await self.browser.main_tab.wait_for(self.selectors.interactions.textbox, timeout = 5)
        except:
            raise CouldNotFindElement("Could not find the textbox")

        chat_id_in_url = await self.browser.main_tab.evaluate(
            f"window.location.href.includes('{chat_id}')",
            await_promise = True,
            return_by_value = True
        )

        if not chat_id_in_url:
            raise InvalidChatID("The chat id is invalid")
        
        self._chat_id = chat_id
        self.logger.debug("Chat switched!")
    
    async def switch_theme(self, theme: Theme):
        """Switches the theme of the chat.

        Args
        ---------
            theme (Theme): The theme to switch to.
        
        Raises
        ---------
            MissingInitialization: If the initialize method is not run before using this method.
        """

        if not self._initialized:
            raise MissingInitialization("You must run the initialize method before using this method.")

        self.logger.debug(f"Switching the theme to: {theme.value}")
        await self.browser.main_tab.evaluate(
            f"localStorage.setItem('__appKit_@deepseek/chat_themePreference', JSON.stringify({{value: '{theme.value}', __version: '0'}}))",
            await_promise = True,
            return_by_value = True
        )

        await self.browser.main_tab.reload()
        self.logger.debug("Theme switched!")


        # does not work, couldnt figure out how to select an option in a dropdown
        # self.logger.debug(f"Switching the theme to: {theme.name}")
        # profile_button = await self.browser.main_tab.select(self.selectors.interactions.profile_button)
        # await profile_button.click()

        # profile_options_dropdown = await self.browser.main_tab.select(self.selectors.interactions.profile_options_dropdown)
        # await profile_options_dropdown.click()

        # settings_button = await self._find_child_by_text(
        #     parent = profile_options_dropdown,
        #     text = "Settings",
        #     in_depth = True
        # )
        # if not settings_button:
        #     raise CouldNotFindElement("Could not find the settings button")
        # await settings_button.click()

        # theme_select_parent = await self.browser.main_tab.select_all(self.selectors.interactions.theme_select_parent)
        # # click the actual theme select, use -1 since the last is the theme
        # # await theme_select_parent[-1].children[0].click()
        # await theme_select_parent[-1].children[0].mouse_click() # this works, but try with headless later
        # # try_another = False
        # # await sleep(3)
        # # breakpoint()
        # # if try_another:
        # #     await theme_select_parent[-1].children[1].mouse_click()
        # await sleep(5)
        
        # for child in theme_select_parent[-1].children[0].children:
        #     if child.text_all.lower() == theme.name.lower(): # figure this out TODO
        #         await child.mouse_click()
        #         break

        # breakpoint()
