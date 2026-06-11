@echo off
title PUMA Client

echo Starting Python script in Conda environment 'ysq'...

call conda activate ysq 
python client.py

echo.
echo Script has finished. Press any key to exit.
pause