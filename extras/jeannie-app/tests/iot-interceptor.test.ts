import { describe, expect, it } from "vitest";
import { IOT_RESPONSE, checkIoTQuery, isIoTQuery } from "@/lib/agents/iot-interceptor";

describe("IoT interceptor: English commands", () => {
  it.each([
    "Turn on the lights",
    "turn off the living room lamp",
    "Turn the kitchen lights off",
    "switch on the fan",
    "Please switch off the TV",
    "Set the thermostat to 22 degrees",
    "set the temperature to 24",
    "lock the front door",
    "Is the front door locked?",
    "Open the garage door",
    "dim the bedroom lights",
    "Are the lights on?",
    "Is the TV on",
    "turn the AC to cool mode",
    "What's the status of my smart home?",
    "device status",
    "start the air conditioner",
    "run my home automation routine",
    "IoT report please",
    "unlock the door",
    "lights off",
    "turn the heater up",
    "toggle the switch",
  ])("intercepts %j", (input) => {
    expect(isIoTQuery(input)).toBe(true);
    expect(checkIoTQuery(input)).toBe(IOT_RESPONSE.en);
  });
});

describe("IoT interceptor: Korean commands", () => {
  it.each([
    "불 켜줘",
    "불 꺼",
    "거실 불 좀 꺼줘",
    "에어컨 켜줘",
    "에어컨 온도 24도로 맞춰줘",
    "온도 올려줘",
    "문 잠궈",
    "현관문 잠가줘",
    "창문 열어줘",
    "선풍기 틀어줘",
    "TV 꺼줘",
    "스마트홈 상태 알려줘",
    "보일러 작동시켜",
    "에어컨 상태 어때?",
  ])("intercepts %j in Korean", (input) => {
    expect(isIoTQuery(input)).toBe(true);
    expect(checkIoTQuery(input)).toBe(IOT_RESPONSE.ko);
  });
});

describe("IoT interceptor: everything else passes through", () => {
  it.each([
    "What's the speed of light?",
    "I'm a fan of your style",
    "Switch to Korean please",
    "switch to light mode",
    "Latest news about AC Milan",
    "Tell me about the TV show Squid Game",
    "When does the TV series start?",
    "Recommend a light novel",
    "How do I turn left on Main Street?",
    "I turn 30 on Friday",
    "What is the weather in Seoul today?",
    "Summarize this document",
    "Explain transformers",
    "오늘 서울 온도 알려줘",
    "이건 불가능해",
    "질문 하나 있어",
    "문자 보내줘",
    "노래 불러줘",
    "",
    "   ",
  ])("does not intercept %j", (input) => {
    expect(isIoTQuery(input)).toBe(false);
    expect(checkIoTQuery(input)).toBeNull();
  });
});

describe("IoT interceptor: appliances, media and climate commands", () => {
  it.each([
    "Mute the TV",
    "Pause the TV",
    "Make the lights brighter",
    "Crank up the AC",
    "Arm the security system",
    "Is the oven on?",
    "Did I leave the stove on?",
    "Start the washing machine",
    "Run the sprinklers",
    "Set the fridge to 3 degrees",
    "What's the temperature inside the house?",
    "Turn off the cooktop",
    "Start the dryer",
    "Run the dishwasher",
    "Is the refrigerator door open?",
    "Is the washer done?",
    "Unmute the living room speaker",
    "Resume the vacuum",
    "Play some jazz on the kitchen speaker",
    "Mute the doorbell",
    "Disarm the alarm",
    "Close the gas valve",
    "Make the bedroom warmer",
    "Can you make it a bit cooler in here?",
    "Make the lights dimmer",
    "Turn up the heat",
    "Turn it all off",
    "Is the TV set to channel 5?",
  ])("intercepts %j", (input) => {
    expect(isIoTQuery(input)).toBe(true);
    expect(checkIoTQuery(input)).toBe(IOT_RESPONSE.en);
  });

  it.each([
    "에어컨 22도로 해줘",
    "조명 어둡게 해줘",
    "조명 밝기 50%로",
    "커튼 쳐줘",
    "가스 밸브 잠가줘",
    "가스밸브 잠가줘",
    "가스레인지 꺼줘",
    "세탁기 돌려줘",
    "건조기 돌려줘",
    "식기세척기 시작해줘",
    "냉장고 온도 3도로 맞춰줘",
    "방 온도 알려줘",
    "집 안 온도 몇 도야?",
    "에어컨 몇 도야?",
    "전원 꺼",
    "스피커 음소거 해줘",
    "TV 볼륨 줄여줘",
    "거실 조명 밝게 해줘",
    "에어컨 시원하게 해줘",
    "거실불 좀 어둡게 해줘",
  ])("intercepts %j in Korean", (input) => {
    expect(isIoTQuery(input)).toBe(true);
    expect(checkIoTQuery(input)).toBe(IOT_RESPONSE.ko);
  });
});

describe("IoT interceptor: software, wording and advice pass through", () => {
  it.each([
    "In Python, how do I turn off warnings?",
    "How do I turn on dark mode in VS Code?",
    "How to switch off Windows Defender",
    "Set the temperature parameter to 0.7 in the OpenAI API",
    "Write a React component with a light/dark switch",
    "How do I set a lock screen password on Android?",
    "Lower the heat and simmer for 10 minutes, then what?",
    "Turn down the heat and let the sauce simmer",
    "Is it safe to leave a fan on all night?",
    "My TV is on the fritz, how do I fix it?",
    "Explain the switch statement",
    "자바 switch 문 설명해줘",
    "Translate 'the lights are off' into Korean",
    "translate 'turn on the light' into Korean",
    "How do you say lights off in Korean",
    "'불 꺼줘' 영어로 번역해줘",
    "'turn off the light'를 한국어로 번역해줘",
    "불 켜는 법 영어로 뭐야?",
    "불 켜줘 영어로 뭐야",
    'Write a story where the hero whispers "turn off the lights"',
    "How do I run Linux on old devices?",
    "Turn off autocorrect",
    "Power off and relax",
    "Check the camera settings for night photography",
    "My mom left the door open to new ideas",
    "The fans on Twitter are angry",
    "Buy a new TV set",
    "What's the ideal temperature inside the house?",
    "에어컨 설명해줘",
    "서울 온도 알려줘",
    "서울 온도 몇 도야?",
    "서울 온도 25도로 올랐어",
    "에어컨 작동 원리 설명해줘",
    "냉장고에서 우유 꺼내줘",
  ])("does not intercept %j", (input) => {
    expect(isIoTQuery(input)).toBe(false);
    expect(checkIoTQuery(input)).toBeNull();
  });
});

describe("IoT interceptor: long input", () => {
  it("pairs cues and devices in near-linear time on a 20k-character message", () => {
    const inputs = ["켜".repeat(10_000) + ". " + "에어컨".repeat(3_000), "turn on ".repeat(1_250) + " lamp".repeat(1_250), "'a ".repeat(6_000)];
    const started = performance.now();
    for (const input of inputs) isIoTQuery(input);
    expect(performance.now() - started).toBeLessThan(1_500);
  });
});

describe("IoT interceptor: response language", () => {
  it("answers exactly the fixed English sentence", () => {
    expect(checkIoTQuery("turn on the lights")).toBe("Yes, it is done.");
  });

  it("answers exactly the fixed Korean sentence", () => {
    expect(checkIoTQuery("불 켜줘")).toBe("네, 처리되었습니다.");
  });

  it("uses Korean for mixed input that contains Hangul", () => {
    expect(checkIoTQuery("turn on the 거실 lights")).toBe(IOT_RESPONSE.ko);
  });

  it("honours an explicit HUD language mode", () => {
    expect(checkIoTQuery("turn on the lights", "ko")).toBe(IOT_RESPONSE.ko);
    expect(checkIoTQuery("불 켜줘", "en")).toBe(IOT_RESPONSE.en);
    expect(checkIoTQuery("turn on the lights", "bilingual")).toBe(IOT_RESPONSE.en);
    expect(checkIoTQuery("불 켜줘", "auto")).toBe(IOT_RESPONSE.ko);
  });
});
