import csv
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import openpyxl


class FileReader:
    """Читает различные форматы файлов и возвращает данные."""
    
    @staticmethod
    def detect_file_type(file_path: str) -> str:
        """Определяет тип файла по расширению."""
        ext = Path(file_path).suffix.lower()
        if ext in ['.xlsx', '.xls']:
            return 'excel'
        elif ext == '.csv':
            return 'csv'
        elif ext == '.json':
            return 'json'
        elif ext == '.jsonl':
            return 'jsonl'
        else:
            return 'unknown'
    
    @staticmethod
    def read_excel_sheets(file_path: str) -> List[str]:
        """Возвращает список листов в Excel-файле."""
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            sheets = wb.sheetnames
            wb.close()
            return sheets
        except Exception as e:
            raise Exception(f"Не удалось открыть Excel-файл: {str(e)}")
    
    @staticmethod
    def read_excel_preview(
        file_path: str,
        sheet_name: str,
        max_rows: int = 100
    ) -> Dict[str, Any]:
        """Читает первые строки Excel-файла для превью."""
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            ws = wb[sheet_name]
            
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= max_rows:
                    break
                rows.append([str(cell) if cell is not None else '' for cell in row])
            
            wb.close()
            
            if not rows:
                return {'headers': [], 'rows': []}
            
            headers = rows[0] if rows else []
            data_rows = rows[1:] if len(rows) > 1 else []
            
            return {'headers': headers, 'rows': data_rows}
        except Exception as e:
            raise Exception(f"Не удалось прочитать Excel-файл: {str(e)}")
    
    @staticmethod
    def read_csv_preview(
        file_path: str,
        encoding: str = 'utf-8',
        delimiter: str = ',',
        max_rows: int = 100
    ) -> Dict[str, Any]:
        """Читает первые строки CSV-файла для превью."""
        try:
            rows = []
            with open(file_path, 'r', encoding=encoding) as f:
                reader = csv.reader(f, delimiter=delimiter)
                for i, row in enumerate(reader):
                    if i >= max_rows:
                        break
                    rows.append(row)
            
            if not rows:
                return {'headers': [], 'rows': []}
            
            headers = rows[0]
            data_rows = rows[1:]
            
            return {'headers': headers, 'rows': data_rows}
        except UnicodeDecodeError:
            raise Exception("Не удалось определить кодировку. Попробуйте выбрать другую.")
        except Exception as e:
            raise Exception(f"Не удалось прочитать CSV-файл: {str(e)}")
    
    @staticmethod
    def read_json_preview(file_path: str, max_rows: int = 100) -> Dict[str, Any]:
        """Читает первые строки JSON-файла для превью."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Проверяем, что это список объектов
            if not isinstance(data, list):
                raise Exception("JSON должен содержать массив объектов")
            
            if not data:
                return {'headers': [], 'rows': []}
            
            # Берём заголовки из первого объекта
            headers = list(data[0].keys())
            
            rows = []
            for item in data[:max_rows]:
                row = [str(item.get(h, '')) for h in headers]
                rows.append(row)
            
            return {'headers': headers, 'rows': rows}
        except json.JSONDecodeError as e:
            raise Exception(f"Ошибка парсинга JSON: {str(e)}")
        except Exception as e:
            raise Exception(f"Не удалось прочитать JSON-файл: {str(e)}")
    
    @staticmethod
    def read_jsonl_preview(file_path: str, max_rows: int = 100) -> Dict[str, Any]:
        """Читает первые строки JSONL-файла для превью."""
        try:
            rows = []
            headers = []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    if i >= max_rows:
                        break
                    
                    line = line.strip()
                    if not line:
                        continue
                    
                    item = json.loads(line)
                    
                    # Берём заголовки из первой строки
                    if not headers:
                        headers = list(item.keys())
                    
                    row = [str(item.get(h, '')) for h in headers]
                    rows.append(row)
            
            return {'headers': headers, 'rows': rows}
        except json.JSONDecodeError as e:
            raise Exception(f"Ошибка парсинга JSONL: {str(e)}")
        except Exception as e:
            raise Exception(f"Не удалось прочитать JSONL-файл: {str(e)}")
    
    @staticmethod
    def read_excel_data(
        file_path: str,
        sheet_name: str,
        header_row: int = 0
    ) -> List[Dict[str, Any]]:
        """Читает все данные из Excel-файла."""
        try:
            wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
            ws = wb[sheet_name]
            
            rows = list(ws.iter_rows(values_only=True))
            wb.close()
            
            if not rows or header_row >= len(rows):
                return []
            
            headers = [str(h) if h else f"col_{i}" for i, h in enumerate(rows[header_row])]
            data = []
            
            for row in rows[header_row + 1:]:
                if all(cell is None or str(cell).strip() == '' for cell in row):
                    continue
                
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(row):
                        value = row[i]
                        row_dict[header] = str(value) if value is not None else ''
                    else:
                        row_dict[header] = ''
                data.append(row_dict)
            
            return data
        except Exception as e:
            raise Exception(f"Ошибка чтения Excel: {str(e)}")
    
    @staticmethod
    def read_csv_data(
        file_path: str,
        encoding: str = 'utf-8',
        delimiter: str = ',',
        header_row: int = 0
    ) -> List[Dict[str, Any]]:
        """Читает все данные из CSV-файла."""
        try:
            rows = []
            with open(file_path, 'r', encoding=encoding) as f:
                reader = csv.reader(f, delimiter=delimiter)
                rows = list(reader)
            
            if not rows or header_row >= len(rows):
                return []
            
            headers = [h if h else f"col_{i}" for i, h in enumerate(rows[header_row])]
            data = []
            
            for row in rows[header_row + 1:]:
                if all(cell.strip() == '' for cell in row):
                    continue
                
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(row):
                        row_dict[header] = row[i]
                    else:
                        row_dict[header] = ''
                data.append(row_dict)
            
            return data
        except UnicodeDecodeError:
            raise Exception("Ошибка кодировки")
        except Exception as e:
            raise Exception(f"Ошибка чтения CSV: {str(e)}")
    
    @staticmethod
    def read_json_data(file_path: str) -> List[Dict[str, Any]]:
        """Читает все данные из JSON-файла."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                raise Exception("JSON должен содержать массив объектов")
            
            result = []
            for item in data:
                # Пропускаем пустые объекты
                if not item:
                    continue
                
                # Конвертируем все значения в строки
                row_dict = {}
                for key, value in item.items():
                    if isinstance(value, (dict, list)):
                        row_dict[key] = json.dumps(value, ensure_ascii=False)
                    else:
                        row_dict[key] = str(value) if value is not None else ''
                
                result.append(row_dict)
            
            return result
        except json.JSONDecodeError as e:
            raise Exception(f"Ошибка парсинга JSON: {str(e)}")
        except Exception as e:
            raise Exception(f"Ошибка чтения JSON: {str(e)}")
    
    @staticmethod
    def read_jsonl_data(file_path: str) -> List[Dict[str, Any]]:
        """Читает все данные из JSONL-файла."""
        try:
            result = []
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        item = json.loads(line)
                        
                        # Конвертируем все значения в строки
                        row_dict = {}
                        for key, value in item.items():
                            if isinstance(value, (dict, list)):
                                row_dict[key] = json.dumps(value, ensure_ascii=False)
                            else:
                                row_dict[key] = str(value) if value is not None else ''
                        
                        result.append(row_dict)
                    except json.JSONDecodeError:
                        # Пропускаем некорректные строки
                        continue
            
            return result
        except Exception as e:
            raise Exception(f"Ошибка чтения JSONL: {str(e)}")