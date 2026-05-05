class ProviderError(Exception):
	pass


class ProviderRateLimitError(ProviderError):
	def __init__(self, message="Rate limit exceeded", retry_after=None):
		super().__init__(message)
		self.retry_after = retry_after


class ProviderAuthError(ProviderError):
	pass


class ProviderContextLengthError(ProviderError):
	pass


class BaseProvider:
	def __init__(self, settings: dict):
		self.api_key = settings.get("api_key", "")
		self.model = settings.get("model", "")
		self.max_tokens = settings.get("max_tokens", 8192)
		self.temperature = settings.get("temperature", 0.7)
		self.api_base_url = settings.get("api_base_url", "")

	def chat(self, messages: list, tools: list = None) -> dict:
		raise NotImplementedError

	def stream(self, messages: list, tools: list = None):
		raise NotImplementedError

	def count_tokens(self, messages: list) -> int:
		raise NotImplementedError

	def supports_tools(self) -> bool:
		raise NotImplementedError

	def supports_vision(self) -> bool:
		raise NotImplementedError

	def get_context_window(self) -> int:
		raise NotImplementedError
