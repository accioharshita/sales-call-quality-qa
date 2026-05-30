import streamlit as st
import os
import uuid
import shutil
import tempfile
from pathlib import Path
import streamlit.components.v1 as components

# Import pipeline services directly
from src.transcribe import transcribe
from src.api.services import stt_service, clean_service, analysis_service, report_service

st.set_page_config(page_title="Sales Quality Agent", layout="wide")

st.title("Sales Quality Agent")
st.write("Upload an audio file (or transcript) along with the course data to generate a full QA report.")

with st.sidebar:
    st.header("Input Parameters")
    
    upload_mode = st.radio("Input Type", ["Audio File", "Transcript File (.json/.txt/.srt/.vtt)"])
    
    if upload_mode == "Audio File":
        audio_file = st.file_uploader("Upload Audio (mp3, wav, etc.)", type=["mp3", "wav", "flac", "m4a", "ogg", "webm"])
        transcript_file = None
    else:
        transcript_file = st.file_uploader("Upload Transcript", type=["json", "txt", "srt", "vtt"])
        audio_file = None
        
    course_file = st.file_uploader("Upload Course Data (CSV)", type=["csv", "md", "txt"])
    sales_pitch_file = st.file_uploader("Upload Sales Pitch (Markdown/Text) (Optional)", type=["md", "txt"])
    
    st.subheader("Metadata")
    rep_name = st.text_input("Sales Rep Name (Optional)")
    rep_id = st.text_input("Sales Rep ID (Optional)")
    customer_name = st.text_input("Customer Name (Optional)")
    call_id = st.text_input("Call ID (Optional)")
    
    model = st.text_input("Model", value="google/gemma-3-27b-it")

    run_pipeline = st.button("Run Pipeline", type="primary", use_container_width=True)

if run_pipeline:
    if not (audio_file or transcript_file):
        st.error("Please upload either an audio file or a transcript.")
        st.stop()
    if not course_file:
        st.error("Please upload the course data.")
        st.stop()

    # Create a temporary directory for the uploads
    temp_dir = tempfile.mkdtemp(prefix="sqa_")
    pipeline_id = uuid.uuid4().hex
    
    try:
        # Save inputs
        course_path = os.path.join(temp_dir, course_file.name)
        with open(course_path, "wb") as f:
            f.write(course_file.getvalue())
            
        sales_pitch_path = None
        if sales_pitch_file:
            sales_pitch_path = os.path.join(temp_dir, sales_pitch_file.name)
            with open(sales_pitch_path, "wb") as f:
                f.write(sales_pitch_file.getvalue())

        saved_transcript_path = None
        saved_audio_path = None
        
        # Use st.status for better step-by-step UX without a background API
        with st.status("Executing Pipeline...", expanded=True) as status:
            if audio_file:
                st.write("🎙️ Processing Audio with STT (Deepgram)...")
                saved_audio_path = os.path.join(temp_dir, audio_file.name)
                with open(saved_audio_path, "wb") as f:
                    f.write(audio_file.getvalue())
                
                # Transcribe directly
                utterances = transcribe(Path(saved_audio_path))
                
                # Use stt_service to save transcript and identify speakers
                saved_transcript_path, extracted_rep_name = stt_service.save_transcript(
                    pipeline_id=pipeline_id,
                    audio_path=saved_audio_path,
                    utterances=utterances
                )
                if not rep_name and extracted_rep_name:
                    rep_name = extracted_rep_name
                    
            else:
                st.write("📄 Reading Transcript...")
                saved_transcript_path = os.path.join(temp_dir, transcript_file.name)
                with open(saved_transcript_path, "wb") as f:
                    f.write(transcript_file.getvalue())

            st.write("🧹 Cleaning and Formatting Transcript...")
            clean_result = clean_service.run_clean(
                pipeline_id=pipeline_id,
                transcript_path=saved_transcript_path,
                rep_speaker=rep_id if rep_id else (rep_name if rep_name else None),
                customer_name=customer_name if customer_name else None,
                sales_rep_name=rep_name if rep_name else None,
            )
            
            cleaned_vtt_path = clean_result["cleaned_vtt_path"]
            stats = clean_result["stats"]

            st.write(f"🧠 Running Analysis (Model: {model})...")
            analysis_result = analysis_service.run_analysis(
                pipeline_id=pipeline_id,
                cleaned_vtt_path=cleaned_vtt_path,
                course_path=course_path,
                sales_pitch_path=sales_pitch_path,
                model=model,
                call_id=call_id,
                call_recording_file=saved_audio_path if saved_audio_path else None,
                call_stt_file=saved_transcript_path,
                sales_rep_name=stats.get("sales_rep_name"),
                sales_rep_id=rep_id,
                customer_name=stats.get("customer_name"),
                call_duration=stats.get("duration_str"),
                no_of_words=stats.get("total_words"),
                stats=stats,
            )
            
            report_json_path = analysis_result["report_json_path"]

            st.write("📊 Generating HTML Report...")
            html_path = report_service.run_report_html(pipeline_id, report_json_path)
            
            status.update(label="Pipeline completed successfully!", state="complete", expanded=False)

        st.subheader("Final Report")
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        components.html(html_content, height=800, scrolling=True)

        st.download_button(
            label="Download HTML Report",
            data=html_content,
            file_name=f"report_{pipeline_id}.html",
            mime="text/html"
        )
        
    except Exception as e:
        st.error(f"Pipeline failed: {e}")
    finally:
        # Cleanup temp directory for uploaded files
        shutil.rmtree(temp_dir, ignore_errors=True)
