from dataclasses import dataclass, field


@dataclass
class LoginSelectors:
    email_input: str = 'input[type="text"]'
    password_input: str = 'input[type="password"]'
    confirm_checkbox: str = 'div[class="ds-checkbox ds-checkbox--none ds-checkbox--bordered"]'
    login_button: str = 'div[role="button"]'

@dataclass
class InteractionSelectors:
    textbox: str = 'textarea[class="_27c9245"]'
    send_options_parent: str = 'div[class="ec4f5d61"]'
    send_button: str = 'div[class="_6f28693"]'
    response_toolbar: str = 'div[class="ds-flex abe97156"]'
    reset_chat_button: str = 'div[class="e214291b"]'
    search_results: str = 'div[class="fe369d61 f529c936"]'
    deepthink_content: str = 'div[class="e1675d8b"]'
    profile_button: str = 'div[class="ede5bc47"]'
    profile_options_dropdown: str = 'div[class="ds-floating-position-wrapper ds-theme"]'
    confirm_deletion_button: str = 'div[class="ds-button ds-button--error ds-button--filled ds-button--rect ds-button--m"]'
    theme_select_parent: str = 'div[class="ds-native-select ds-native-select--filled ds-native-select--none ds-native-select--m"]'

@dataclass
class BackendSelectors:
    response_generating: str = 'div[class="_4f9bf79 d7dc56a8"]'
    response_generated: str = 'div[class="_4f9bf79 d7dc56a8 _43c05b5"]'
    regen_loading_icon: str = 'div[class="ds-loading b4e4476b"]'
    response_toolbar_b64: str = 'ds-flex abe97156'  # This is different, because it's used in BS4

@dataclass
class URLSelectors:
    chat_url: str = "https://chat.deepseek.com/"

@dataclass
class DeepSeekSelectors:
    login: LoginSelectors = field(default_factory=LoginSelectors)
    interactions: InteractionSelectors = field(default_factory=InteractionSelectors)
    backend: BackendSelectors = field(default_factory=BackendSelectors)
    urls: URLSelectors = field(default_factory=URLSelectors)
