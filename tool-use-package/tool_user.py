from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT
import re
import builtins
import ast

from .prompt_constructors import construct_use_tools_prompt, construct_successful_function_run_injection_prompt, construct_error_function_run_injection_prompt

class ToolUser:
    def __init__(self, tools, temperature=0, max_retries=3):
        self.tools = tools
        self.temperature = temperature
        self.max_retries = max_retries
        self.anthropic = Anthropic()
        self.current_prompt = None
        self.current_num_retries = 0
    
    def use_tools(self, prompt):
        constructed_prompt = construct_use_tools_prompt(prompt, self.tools)
        
        self.current_prompt = constructed_prompt
        
        completion = self.anthropic.completions.create(
            model="claude-2",
            max_tokens_to_sample=2000,
            temperature=self.temperature,
            prompt=self.current_prompt
        )
        
        parsed_function_calls = self._parse_function_calls(completion.completion)
        if parsed_function_calls['status'] == 'DONE':
            return completion.completion
        
        while True:
            claude_response = self._construct_next_injection(parsed_function_calls)
            self.current_prompt = (
                f"{self.current_prompt}\n\n"
                f"{completion.completion}\n\n"
                f"{claude_response}"
            )

            completion = self.anthropic.completions.create(
                model="claude-2",
                max_tokens_to_sample=2000,
                temperature=self.temperature,
                prompt=self.current_prompt
            )

            parsed_function_calls = self._parse_function_calls(completion.completion)
            if parsed_function_calls['status'] == 'DONE':
                return completion.completion
    
    def _parse_function_calls(self, last_completion):
        # Check if the format of the function call is valid
        invoke_calls = ToolUser._function_calls_valid_format_and_invoke_extraction(last_completion)
        if not invoke_calls['status']:
            return {"status": "ERROR", "message": invoke_calls['reason']}
        
        if not invoke_calls['invokes']:
            return {"status": "DONE"}
        
        # Parse the query's invoke calls and get it's results
        invoke_results = []
        for invoke_call in invoke_calls['invokes']:
            # Find the correct tool instance
            tool_name = invoke_call['tool_name']
            tool = next((t for t in self.tools if t.name == tool_name), None)
            if tool is None:
                return {"status": "ERROR", "message": f"No tool named <tool_name>{tool_name}</tool_name> available."}
            
            # Validate the provided parameters
            parameters = invoke_call['parameters_with_values']
            parameter_names = [p['name'] for p in tool.parameters]
            provided_names = [p[0] for p in parameters]

            invalid = set(provided_names) - set(parameter_names)
            missing = set(parameter_names) - set(provided_names)
            if invalid:
                return {"status": "ERROR", "message": f"Invalid parameters {invalid} for <tool_name>{tool_name}</tool_name>."}
            if missing:
                return {"status": "ERROR", "message": f"Missing required parameters {parameter_names} for <tool_name>{tool_name}</tool_name>."}
            
            # Convert values and call tool
            converted_params = {}
            for name, value in parameters:
                param_def = next(p for p in tool.parameters if p['name'] == name)
                type_ = param_def['type']
                converted_params[name] = ToolUser._convert_value(value, type_)
            
            invoke_results.append((tool_name, tool.use_tool(**converted_params)))
        
        return {"status": "SUCCESS", "invoke_results": invoke_results}
    
    def _construct_next_injection(self, invoke_results):
        if invoke_results['status'] == 'SUCCESS':
            self.current_num_retries = 0
            return construct_successful_function_run_injection_prompt(invoke_results['invoke_results'])
        elif invoke_results['status'] == 'ERROR':
            if self.current_num_retries == self.max_retries:
                raise ValueError("Hit maximum number of retries attempting to use tools.")
            
            self.current_num_retries +=1
            return construct_error_function_run_injection_prompt(invoke_results['message'])
        else:
            raise ValueError(f"Unrecognized status from invoke_results, {invoke_results['status']}.")    
    
    @staticmethod
    def _function_calls_valid_format_and_invoke_extraction(last_completion):
        """Check if the function call follows a valid format and extract the attempted function calls if so. Does not check if the tools actually exist or if they are called with the requisite params."""
        # Check if there are any of the relevant XML tags present that would indicate an attempted function call.
        function_call_tags = re.findall(r'<function_calls>|</function_calls>|<invoke>|</invoke>|<tool_name>|</tool_name>|<parameters>|</parameters>', last_completion, re.DOTALL)
        if not function_call_tags:
            # TODO: Should we return something in the text to claude indicating that it did not do anything to indicate an attempted function call (in case it was in fact trying to and we missed it)?
            return {"status": True, "invokes": []}
        
        # Extract content between <function_calls> tags. If there are multiple we will only parse the first and ignore the rest, regardless of their correctness.
        match = re.search(r'<function_calls>(.*)</function_calls>', last_completion, re.DOTALL)
        if not match:
            return {"status": False, "reason": "No valid <function_calls></function_calls> tags present in your query."}
        
        func_calls = match.group(1)
       
        # Check for invoke tags
        # TODO: Is this faster or slower than bundling with the next check?
        invoke_regex = r'<invoke>.*?</invoke>'
        if not re.search(invoke_regex, func_calls, re.DOTALL):
            return {"status": False, "reason": "Missing <invoke></invoke> tags inside of <function_calls></function_calls> tags."}
       
        # Check each invoke contains tool name and parameters
        invoke_strings = re.findall(invoke_regex, func_calls, re.DOTALL)
        invokes = []
        for invoke_string in invoke_strings:
            # TODO: should check if there are more than one set of these (there shouldn't be)
            tool_name = re.findall(r'<tool_name>.*?</tool_name>', invoke_string, re.DOTALL)
            if not tool_name:
                return {"status": False, "reason": "Missing <tool_name></tool_name> tags inside of <invoke></invoke> tags."}
            if len(tool_name) > 1:
                return {"status": False, "reason": "More than one tool_name specified inside single set of <invoke></invoke> tags."}

            parameters = re.findall(r'<parameters>.*?</parameters>', invoke_string, re.DOTALL)
            if not parameters:
                return {"status": False, "reason": "Missing <tool_name></tool_name> tags inside of <invoke></invoke> tags."}
            if len(parameters) > 1:
                return {"status": False, "reason": "More than one set of <parameters></parameters> tags specified inside single set of <invoke></invoke> tags."}
            
            # Check for balanced tags inside parameters
            # TODO: This will fail if the parameter value contains <> pattern or if there is a parameter called parameters. Fix that issue.
            tags = re.findall(r'<.*?>', parameters[0].replace('<parameters>', '').replace('</parameters>', ''), re.DOTALL)
            if len(tags) % 2 != 0:
                return {"status": False, "reason": "Imbalanced tags inside <parameters></parameters> tags."}
            
            # Loop through the tags and check if each even-indexed tag matches the tag in the position after it (with the / of course). If valid store their content for later use.
            # TODO: Add a check to make sure there aren't duplicates provided of a given parameter.
            parameters_with_values = []
            for i in range(0, len(tags), 2):
                opening_tag = tags[i]
                closing_tag = tags[i+1]
                closing_tag_without_second_char = closing_tag[:1] + closing_tag[2:]
                if closing_tag[1] != '/' or opening_tag != closing_tag_without_second_char:
                    return {"status": False, "reason": "Non-matching opening and closing tags inside <parameters></parameters> tags."}
                
                parameters_with_values.append((opening_tag[1:-1], re.search(rf'{opening_tag}(.*?){closing_tag}', parameters[0], re.DOTALL).group(1)))
        
            # Parse out the full function call
            invokes.append({"tool_name": tool_name[0].replace('<tool_name>', '').replace('</tool_name>', ''), "parameters_with_values": parameters_with_values})
        
        return {"status": True, "invokes": invokes}
    
    # TODO: This only handles the outer-most type. Nested types are an unimplemented issue at the moment.
    @staticmethod
    def _convert_value(value, type_str):
        if type_str in ("list", "dict"):
            return ast.literal_eval(value)
        
        type_class = getattr(builtins, type_str)
        return type_class(value)