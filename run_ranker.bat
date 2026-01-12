@echo off
chcp 65001 >nul
echo ========================================
echo AI产业链股票量化选股系统 - 快速运行
echo ========================================
echo.

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查依赖是否安装
pip show pandas >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装依赖包...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )
)

echo.
echo [1] 使用模拟数据运行（快速测试）
echo [2] 使用真实数据运行（需要Tushare Token）
echo [3] 生成详细报告
echo [4] 仅显示排名Top 20
echo.

set /p choice="请选择运行模式 [1-4]: "
echo.

if "%choice%"=="1" (
    echo [运行] 使用模拟数据...
    python ai_stock_ranker.py --csv ai_stock_pool.csv --output ranking_result.csv --report
) else if "%choice%"=="2" (
    echo [运行] 使用真实数据...
    echo 请确保已设置TUSHARE_TOKEN环境变量
    set TUSHARE_TOKEN=
    set /p token="请输入Tushare Token (如无请直接回车使用模拟数据): "
    if defined token (
        setx TUSHARE_TOKEN "%token%" >nul
        echo [提示] Token已临时设置
    )
    python ai_stock_ranker.py --csv ai_stock_pool.csv --output ranking_result.csv --report
) else if "%choice%"=="3" (
    echo [运行] 生成详细报告...
    python ai_stock_ranker.py --csv ai_stock_pool.csv --output ranking_result.csv --report
) else if "%choice%"=="4" (
    echo [运行] 显示Top 20...
    python ai_stock_ranker.py --csv ai_stock_pool.csv --report
    echo.
    echo [提示] 完整结果已保存到 ranking_result.csv
) else (
    echo [错误] 无效的选择
    pause
    exit /b 1
)

echo.
echo ========================================
echo 排序完成！
echo ========================================
echo.
echo 输出文件:
echo   - ranking_result.csv: 完整配置结果
echo   - ranking_result_ranking.csv: 详细排名数据
echo.
pause
