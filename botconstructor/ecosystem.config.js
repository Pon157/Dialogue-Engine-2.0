module.exports = {
  apps: [
    {
      name: "dialogue-bot",
      script: "run_bot.py",
      interpreter: "/root/Dialogue-Engine-2.0/botconstructor/venv/bin/python3",
      cwd: "/root/Dialogue-Engine-2.0/botconstructor",
      kill_timeout: 8000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
    {
      name: "master-bot",
      script: "run_master.py",
      interpreter: "/root/Dialogue-Engine-2.0/botconstructor/venv/bin/python3",
      cwd: "/root/Dialogue-Engine-2.0/botconstructor",
      kill_timeout: 8000,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
