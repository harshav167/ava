"""
Tests for OpenAI error parsing functionality.
"""

import pytest
from unittest.mock import Mock, MagicMock, PropertyMock
from voice_mode.openai_error_parser import OpenAIErrorParser


class TestOpenAIErrorParser:
    """Test the OpenAIErrorParser class."""

    def test_parse_quota_exceeded_error(self):
        """Test parsing of quota exceeded errors."""
        # Create a mock exception with quota error
        mock_exception = Mock()
        mock_response = Mock()
        # Set attributes directly
        mock_response.status_code = 429
        mock_response.text = "You've exceeded your current quota, please check your plan and billing details"
        mock_exception.response = mock_response
        mock_exception.__str__ = Mock(return_value="insufficient_quota")

        result = OpenAIErrorParser.parse_error(mock_exception, endpoint="https://api.openai.com/v1/audio/speech")

        assert result['title'] == '💳 OpenAI Quota Exceeded'
        assert 'quota has been exceeded' in result['message']
        assert 'Check your OpenAI account' in result['suggestion']
        assert 'local voice services' in result['fallback']
        # Status code should be present in result
        assert 'status_code' in result

    def test_parse_invalid_api_key_error(self):
        """Test parsing of invalid API key errors."""
        # Create a mock exception with auth error
        mock_exception = Mock()
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key provided"
        mock_exception.response = mock_response
        mock_exception.__str__ = Mock(return_value="Invalid API key")

        result = OpenAIErrorParser.parse_error(mock_exception)

        assert result['title'] == '🔐 OpenAI Authentication Failed'
        assert 'invalid or missing' in result['message']
        assert 'OPENAI_API_KEY' in result['suggestion']
        assert 'without an API key' in result['fallback']
        assert 'status_code' in result

    def test_parse_rate_limit_error(self):
        """Test parsing of rate limit errors (not quota)."""
        # Create a mock exception with rate limit error
        mock_exception = Mock()
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit reached for requests"
        mock_exception.response = mock_response
        mock_exception.__str__ = Mock(return_value="Rate limit exceeded")

        result = OpenAIErrorParser.parse_error(mock_exception)

        assert result['title'] == '⏱️ OpenAI Rate Limit'
        assert 'rate limit' in result['message']
        assert 'Wait a moment' in result['suggestion']
        assert 'no rate limits' in result['fallback']
        assert 'status_code' in result

    def test_parse_billing_limit_error(self):
        """Test parsing of billing hard limit errors."""
        # Create a mock exception with billing limit error
        mock_exception = Mock()
        mock_exception.response = Mock()
        mock_exception.response.status_code = 429
        mock_exception.response.text = "You have reached your billing hard limit"
        mock_exception.__str__ = Mock(return_value="billing_hard_limit_reached")

        result = OpenAIErrorParser.parse_error(mock_exception)

        assert result['title'] == '💰 OpenAI Billing Limit Reached'
        assert 'billing hard limit' in result['message']
        assert 'increase your spending limit' in result['suggestion']
        assert 'no billing limits' in result['fallback']

    def test_parse_access_terminated_error(self):
        """Test parsing of access terminated errors."""
        # Create a mock exception with access terminated
        mock_exception = Mock()
        mock_exception.response = Mock()
        mock_exception.response.status_code = 403
        mock_exception.response.text = "Your account access has been terminated"
        mock_exception.__str__ = Mock(return_value="Access terminated")

        result = OpenAIErrorParser.parse_error(mock_exception)

        assert result['title'] == '🚫 OpenAI Access Terminated'
        assert 'has been terminated' in result['message']
        assert 'Contact OpenAI support' in result['suggestion']

    def test_parse_unknown_error(self):
        """Test parsing of unknown/generic errors."""
        # Create a mock exception with generic error
        mock_exception = Mock()
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        mock_exception.response = mock_response
        mock_exception.__str__ = Mock(return_value="Something went wrong")

        result = OpenAIErrorParser.parse_error(mock_exception)

        assert result['title'] == '⚠️ OpenAI API Error'
        assert 'OpenAI API error' in result['message']
        assert 'Check your API configuration' in result['suggestion']
        assert 'status_code' in result

    def test_parse_error_without_response(self):
        """Test parsing of errors without response object."""
        # Create a simple exception without response
        mock_exception = Exception("Connection failed")

        result = OpenAIErrorParser.parse_error(mock_exception)

        assert result['title'] == '⚠️ OpenAI API Error'
        assert 'Connection failed' in result['message']
        assert 'raw_error' in result
        assert result['raw_error'] == 'Connection failed'

    def test_format_error_message_with_fallback(self):
        """Test formatting error message with fallback."""
        error_dict = {
            'title': '💳 Test Error',
            'message': 'Test error message',
            'suggestion': 'Test suggestion',
            'fallback': 'Test fallback',
            'status_code': 429
        }

        formatted = OpenAIErrorParser.format_error_message(error_dict, include_fallback=True)

        assert '💳 Test Error' in formatted
        assert 'Test error message' in formatted
        assert '💡 Test suggestion' in formatted
        assert 'ℹ️ Test fallback' in formatted
        assert '[HTTP 429]' in formatted

    def test_format_error_message_without_fallback(self):
        """Test formatting error message without fallback."""
        error_dict = {
            'title': '💳 Test Error',
            'message': 'Test error message',
            'suggestion': 'Test suggestion',
            'fallback': 'Test fallback'
        }

        formatted = OpenAIErrorParser.format_error_message(error_dict, include_fallback=False)

        assert '💳 Test Error' in formatted
        assert 'Test error message' in formatted
        assert '💡 Test suggestion' in formatted
        assert 'ℹ️ Test fallback' not in formatted

    def test_parse_error_with_json_response(self):
        """Test parsing error with JSON response body."""
        # Create exception with JSON response
        mock_exception = Mock()
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API key provided"  # Make text clearer
        mock_response.json = Mock(return_value={
            'error': {
                'code': 'invalid_api_key',
                'message': 'Incorrect API key provided'
            }
        })
        mock_exception.response = mock_response
        mock_exception.__str__ = Mock(return_value="Invalid API key provided")

        result = OpenAIErrorParser.parse_error(mock_exception)

        # With 401 status code, it should detect auth failure
        assert result['title'] == '🔐 OpenAI Authentication Failed'
        assert 'status_code' in result

    def test_extract_error_info_with_openai_attributes(self):
        """Test extracting error info from OpenAI-specific exception attributes."""
        # Create mock exception with OpenAI attributes
        mock_exception = Mock()
        mock_exception.status_code = 429
        mock_exception.error = {
            'code': 'insufficient_quota',
            'message': 'You have exceeded your quota'
        }
        mock_exception.__str__ = Mock(return_value="Quota exceeded")

        info = OpenAIErrorParser._extract_error_info(mock_exception)

        assert info['status_code'] == 429
        assert info['error_dict'] == mock_exception.error
        assert info['error_code'] == 'insufficient_quota'
        assert info['error_message'] == 'You have exceeded your quota'

    def test_determine_error_type_by_message(self):
        """Test determining error type by message content."""
        # Test quota detection by message
        error_info = {
            'message': 'You have insufficient_quota for this request'
        }
        assert OpenAIErrorParser._determine_error_type(error_info) == 'quota_exceeded'

        # Test auth detection by message
        error_info = {
            'message': 'Invalid API key provided'
        }
        assert OpenAIErrorParser._determine_error_type(error_info) == 'auth_failed'

        # Test rate limit detection by message
        error_info = {
            'message': 'Rate limit exceeded, please slow down'
        }
        assert OpenAIErrorParser._determine_error_type(error_info) == 'rate_limit'

    def test_endpoint_included_in_result(self):
        """Test that endpoint is included in the result when provided."""
        mock_exception = Exception("Test error")
        endpoint = "https://api.openai.com/v1/audio/speech"

        result = OpenAIErrorParser.parse_error(mock_exception, endpoint=endpoint)

        assert result['endpoint'] == endpoint