# GUI
pyinstaller --onedir --windowed --noconfirm --clean --icon=logo.ico GUI.py --add-data "logo.ico;."


# Runner 脚本
pyinstaller --onedir --noconfirm --clean mzml_model_trainer.py
pyinstaller --onedir --noconfirm --clean mzml_correction.py
pyinstaller --onedir --noconfirm --clean apply_model_featurelist.py

mkdir spec

pyinstaller --onedir --noconfirm --clean --specpath spec GUI.py --windowed --icon=logo.ico --add-data "logo.ico;."
pyinstaller --onedir --noconfirm --clean --specpath spec mzml_model_trainer.py
pyinstaller --onedir --noconfirm --clean --specpath spec mzml_correction.py
pyinstaller --onedir --noconfirm --clean --specpath spec apply_model_featurelist.py
pyinstaller --onedir --noconfirm --clean --specpath spec area_bias_correction.py

pyinstaller --noconfirm --clean spec\RTCorrectorBundle.spec --upx-dir "D:\OneDrive\upx\upx-5.0.2-win64\upx.exe"
