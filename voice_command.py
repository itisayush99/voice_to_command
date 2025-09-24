import streamlit as st
from audio_recorder_streamlit import audio_recorder
import whisper
import tempfile
import winrm
import paramiko
import socket
import subprocess
import os

from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain

# -------------------- Utility --------------------
def is_port_open(host, port, timeout=3):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except:
            return False

def find_and_launch(app_name):
    """Search common folders for the executable and launch it."""
    common_paths = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        os.path.join(os.environ['USERPROFILE'], r"AppData\Local")
    ]
    
    executable_name = app_name + ".exe"
    found = False
    
    for path in common_paths:
        for root, dirs, files in os.walk(path):
            if executable_name.lower() in [f.lower() for f in files]:
                exe_path = os.path.join(root, executable_name)
                subprocess.Popen(exe_path)
                st.success(f"✅ Launched {app_name} ({exe_path})")
                found = True
                break
        if found:
            break

    if not found:
        st.error(f"Could not find application '{app_name}' in common paths.")

# -------------------- LangChain Setup --------------------
template = """
You are a helpful assistant. Convert the user's request into a valid {machine} command.
Note: If the command cannot be executed using WinRM or SSH, respond exactly with:
Cannot execute command: [brief reason here]

User request: {user_input}

Command:
"""
# Replace the placeholder with your actual OpenAI API key.
openai_api_key = "YOUR_API_KEY_HERE"
prompt = PromptTemplate(template=template, input_variables=["machine","user_input"])
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, openai_api_key=openai_api_key)
chain = LLMChain(llm=llm, prompt=prompt)

# -------------------- Whisper Setup --------------------
model = whisper.load_model("base")

# -------------------- Streamlit UI --------------------
st.title("Voice-Driven Windows/Linux Assistant")

# Step 1: Voice Input
st.header("Record Voice Command")
audio_bytes = audio_recorder("Click to record your command", icon_size="2x")

if audio_bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
        temp_audio.write(audio_bytes)
        temp_path = temp_audio.name

    st.success("✅ Audio recorded. Transcribing...")
    result = model.transcribe(temp_path)
    user_text = result["text"]
    st.subheader("Transcription")
    st.write(user_text)

    # Step 2: Configuration Input
    st.header("Target Machine Configuration")
    host = st.text_input("Target Host (IP or hostname)", value="localhost")
    username = st.text_input("Username", value="YourUsername")
    password = st.text_input("Password", type="password")

    if host and username and password:

        # -------------------- Local Handling --------------------
        if host.lower() == "localhost":
            user_text_lower = user_text.lower()
            is_local_app_command = False
            app_name = ""
            
            # Updated to map to known executables
            known_apps = {
                "notepad": "notepad",
                "calculator": "calc",
                "paint": "mspaint",
                "word": "winword",
                "chrome": "chrome"
            }
            
            # New, more flexible detection logic
            for known, exe_name in known_apps.items():
                if known in user_text_lower:
                    is_local_app_command = True
                    app_name = exe_name
                    break

            if is_local_app_command:
                st.info(f"Detected a local app command. Trying to launch '{app_name}'...")
                try:
                    # Using 'Start-Process' is more reliable
                    subprocess.Popen(['powershell', '-Command', f'Start-Process {app_name}'])
                    st.success(f"✅ {app_name.capitalize()} launched successfully!")
                except Exception as e:
                    st.error(f"Failed to launch {app_name}: {e}")
            else:
                # Only non-app commands go to LangChain
                try:
                    ps_command = chain.run({"machine": "Windows(Powershell)", "user_input": user_text})
                    st.subheader("Generated PowerShell Command")
                    st.code(ps_command, language="powershell")

                    if ps_command.lower().startswith("cannot execute command"):
                        st.error(ps_command)
                    else:
                        ps_result = subprocess.run(
                            ["powershell", "-Command", ps_command],
                            capture_output=True, text=True
                        )
                        if ps_result.stdout:
                            st.subheader("PowerShell Output")
                            st.text(ps_result.stdout)
                        if ps_result.stderr:
                            st.error(ps_result.stderr)
                except Exception as e:
                    st.error(f"Failed to run PowerShell command: {e}")

        # -------------------- Remote Handling --------------------
        if host.lower() != "localhost":
            if is_port_open(host, 5985):
                st.info("Detected WinRM (Windows)")
                command = chain.run({"machine": "Windows(Powershell)", "user_input": user_text})

                if command.lower().startswith("cannot execute command"):
                    st.error(command)
                else:
                    st.subheader("Generated Command")
                    st.code(command, language="powershell")

                    session = winrm.Session(f'http://{host}:5985/wsman', auth=(username, password), transport='ntlm')
                    result = session.run_ps(command)

                    st.subheader("Output (WinRM)")
                    if result.status_code == 0:
                        st.text(result.std_out.decode())
                    else:
                        st.error(result.std_err.decode())

            elif is_port_open(host, 22):
                st.info("Detected SSH")
                command = chain.run({"machine": "SSH", "user_input": user_text})

                if command.lower().startswith("cannot execute command"):
                    st.error(command)
                else:
                    st.subheader("Generated Command")
                    st.code(command, language="bash")

                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(hostname=host, username=username, password=password)

                    stdin, stdout, stderr = ssh.exec_command(command)

                    st.subheader("Output (SSH)")
                    output = stdout.read().decode()
                    error = stderr.read().decode()

                    if output:
                        st.text(output)
                    if error:
                        st.error(error)

                    ssh.close()

            else:
                st.error("Cannot establish connection to the target host")