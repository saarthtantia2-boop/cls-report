/*
  CLASSROOM NOISE DETECTOR
  ------------------------
  Components:
    - 3-pin analog microphone (VCC, GND, OUT)
    - MicroSD card module (SPI)
    - 16x2 I2C LCD
    - Push button (momentary, normally open)

  WIRING (Arduino Uno/Nano):

  Microphone (3-pin):
    VCC  -> 5V
    GND  -> GND
    OUT  -> A0

  SD Card Module (SPI):
    CS   -> D10
    MOSI -> D11
    MOSO -> D12  (same as MISO)
    SCK  -> D13
    VCC  -> 5V
    GND  -> GND

  I2C LCD (color coded):
    GND  (green)  -> GND
    VCC  (yellow) -> 5V
    SDA  (orange) -> A4  (SDA on Uno/Nano)
    SCL  (red)    -> A5  (SCL on Uno/Nano)

  Push Button:
    One leg -> D7
    Other leg -> GND
    (uses internal pull-up, no external resistor needed)

  BEHAVIOR:
    - Row 1: noise level 0-15 (updates every second)
    - Row 2: recording status (Not Recording / Started Recording / Recording...)
    - Press button to start/stop recording
    - Records 8-bit 8kHz mono WAV files to SD card (TMRpcm, interrupt-driven)
    - Auto-advances to next class every 30 minutes
    - Recording filenames: MMDDHHMM.wav (date + 24h time, e.g. 07151330.wav)
    - Noise logged every second to MMDDHHMM.log (new file every 10 min)
      First line of each log is the date, e.g. 2026-07-15
    - Times based on compile time (__TIME__ / __DATE__) — compile just before use

  REQUIRED LIBRARIES (install via Library Manager):
    - LiquidCrystal_I2C by Frank de Brabander
    - SD by Arduino, SPI by Arduino (built-in)
*/

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SPI.h>
#include <SD.h>
#include <TMRpcm.h>

// ===== CONFIG =====
#define MIC_PIN       A0
#define BTN_PIN       7
#define SD_CS         10
#define I2C_ADDR      0x27

// Uses __TIME__ (compile time) as real-time base — compile just before upload
#define BASE_HOUR   ((__TIME__[0] - '0') * 10 + (__TIME__[1] - '0'))
#define BASE_MINUTE ((__TIME__[3] - '0') * 10 + (__TIME__[4] - '0'))
#define BASE_SECOND ((__TIME__[6] - '0') * 10 + (__TIME__[7] - '0'))

#define SAMPLE_RATE   8000
#define AMP_WIN_MS    1000  // noise level refresh (1 sec)
#define DISP_MS       250   // LCD refresh
#define SESSION_MS    1800000  // 30 minutes
#define LOG_SESSION_MS 600000  // new noise log file every 10 minutes

// ===== LCD =====
LiquidCrystal_I2C lcd(I2C_ADDR, 16, 2);
TMRpcm audio;

// ===== Globals =====
// Date (from compile-time __DATE__)
char dateStamp[5];   // "0715" (MMDD)
char dateHeader[11]; // "2026-07-15"
char currentFilename[20];

// Amplitude
int ampMin = 1023, ampMax = 0;
int noise = 0;
unsigned long lastAmpMs = 0;
unsigned long nextSampUs = 0;

// Recording
bool recActive = false;
bool lastBtn = HIGH;
int sessionNum = 1;
unsigned long sesStartMs = 0;

// Noise logging
char logFilename[20];

// Display
enum { IDLE, STARTED, RECING } dispState = IDLE;
unsigned long dispStartMs = 0;
unsigned long lastDispMs = 0;
unsigned long lastBlinkMs = 0;
bool blinkOn = false;

byte circleChar[8] = {
  B00000,
  B01110,
  B11111,
  B11111,
  B11111,
  B01110,
  B00000,
  B00000
};

// ===== Setup =====
void buildDateStrings() {
  const char* months[] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun",
                          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"};
  int mon = 1;
  for (int i = 0; i < 12; i++) {
    if (strncmp(__DATE__, months[i], 3) == 0) { mon = i + 1; break; }
  }
  int day = atoi(__DATE__ + 4);
  int yr  = atoi(__DATE__ + 7);
  sprintf(dateStamp, "%02d%02d", mon, day);
  sprintf(dateHeader, "%04d-%02d-%02d", yr, mon, day);
}

void setup() {
  pinMode(BTN_PIN, INPUT_PULLUP);
  buildDateStrings();

  Wire.begin();
  lcd.begin(16, 2);
  lcd.createChar(0, circleChar);
  lcd.backlight();
  lcd.clear();
  lcd.print("Noise Detector");
  lcd.setCursor(0, 1);
  lcd.print("Init SD...");

  if (!SD.begin(SD_CS)) {
    lcd.setCursor(0, 1);
    lcd.print("smthn wrong in sd");
    while (1);
  }

  audio.CSPin = SD_CS;

  delay(1000);
  lcd.clear();
}

// ===== Main Loop =====
void loop() {
  unsigned long nowMs = millis();
  unsigned long nowUs = micros();

  // --- Sample mic for noise detection (skip while TMRpcm owns the ADC) ---
  if (!recActive && nowUs - nextSampUs >= 125UL) {
    nextSampUs = nowUs;
    int v = analogRead(MIC_PIN);
    if (v < ampMin) ampMin = v;
    if (v > ampMax) ampMax = v;
  }

  // --- Auto-advance recording every SESSION_MS ---
  if (recActive && nowMs - sesStartMs >= SESSION_MS) {
    stopRecording();
    sessionNum++;
    delay(500);
    startRecording();
  }

  // --- Update noise level every AMP_WIN_MS ---
  if (nowMs - lastAmpMs >= AMP_WIN_MS) {
    if (!recActive) {
      int a = ampMax - ampMin;
      noise = constrain(map(a, 0, 1023, 0, 15), 0, 15);
      ampMin = 1023;
      ampMax = 0;
    }
    lastAmpMs = nowMs;

    // Log noise to SD every second (new file every 10 min)
    writeLogLine();
  }

  // --- Button ---
  bool btn = digitalRead(BTN_PIN);
  if (btn == LOW && lastBtn == HIGH) {
    delay(30);
    if (digitalRead(BTN_PIN) == LOW) {
      if (recActive) stopRecording();
      else startRecording();
      while (digitalRead(BTN_PIN) == LOW);
    }
  }
  lastBtn = btn;

  // --- Update display ---
  if (nowMs - lastDispMs >= DISP_MS) {
    updateDisplay(nowMs);
    lastDispMs = nowMs;
  }
}

// ===== Start Recording =====
void startRecording() {
  int totalMin = (BASE_HOUR * 60 + BASE_MINUTE) + (millis() / 60000);
  totalMin %= (24 * 60);
  int h24 = totalMin / 60;
  int m = totalMin % 60;

  sprintf(currentFilename, "%s%02d%02d.wav", dateStamp, h24, m);

  audio.startRecording(currentFilename, SAMPLE_RATE, MIC_PIN);
  recActive = true;
  sesStartMs = millis();
  dispState = STARTED;
  dispStartMs = millis();
}

// ===== Stop Recording =====
void stopRecording() {
  audio.stopRecording(currentFilename);
  recActive = false;
  dispState = IDLE;
}

// ===== Noise Logging =====
void writeLogLine() {
  unsigned long totalSec = (BASE_HOUR * 3600L + BASE_MINUTE * 60L + BASE_SECOND + millis() / 1000) % 86400L;
  int hh = totalSec / 3600;
  int mm = (totalSec % 3600) / 60;
  int ss = totalSec % 60;
  int blockMin = ((totalSec / 60) / 10) * 10;

  sprintf(logFilename, "%s%02d%02d.log", dateStamp, (blockMin / 60) % 24, blockMin % 60);

  File f = SD.open(logFilename, FILE_WRITE);
  if (f) {
    if (f.size() == 0) {
      f.println(dateHeader);
    }
    char line[20];
    sprintf(line, "%02d:%02d:%02d %d\n", hh, mm, ss, noise);
    f.print(line);
    f.close();
  }
}

// ===== Update LCD =====
void updateDisplay(unsigned long nowMs) {
  // Row 0: noise level
  lcd.setCursor(0, 0);
  lcd.print("Noise: ");
  if (noise < 10) lcd.print(' ');
  lcd.print(noise);
  lcd.print("/15   ");

  // Row 1: status
  lcd.setCursor(0, 1);
  switch (dispState) {
    case IDLE:
      lcd.print("Not Recording   ");
      break;
    case STARTED:
      lcd.print("Rec Started!    ");
      if (nowMs - dispStartMs >= 3000) {
        dispState = RECING;
        blinkOn = true;
        lastBlinkMs = nowMs;
      }
      break;
    case RECING:
      if (nowMs - lastBlinkMs >= 750) {
        blinkOn = !blinkOn;
        lastBlinkMs = nowMs;
      }
      lcd.print("Recording  ");
      lcd.write(blinkOn ? 0 : ' ');
      lcd.print("    ");
      break;
  }
}
